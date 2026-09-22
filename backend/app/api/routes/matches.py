"""Match endpoints: queue a match, then spectate its live event stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.agents.agents_directory import agent_mapper, split_model_name
from app.api.schemas.dto_models import (
    MatchEventListResponse,
    MatchEventSchema,
    MatchListResponse,
    MatchListSchema,
    StartMatchRequest,
    StartMatchResponse,
)
from app.broker.events import subscribe_match_events
from app.broker.models import MatchStartMessage
from app.broker.queue import enqueue_match_start
from app.db import get_session
from app.db.models import Challenge, Match
from app.db.services import match_events_service, matches_service
from app.logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/matches", tags=["matches"])

SSE_MEDIA_TYPE = "text/event-stream"

#: Events returned per page by the paginated list endpoints.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

#: SSE keep-alive comments keep proxies from closing an idle connection.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/free-models")
async def list_free_models() -> list[str]:
    """Return the model names (``provider/model``) this deployment can host."""
    return list(agent_mapper)


@router.get("/", response_model=MatchListResponse)
async def list_matches(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    sort: Literal["date_desc", "date_asc"] = Query("date_desc"),
    session: AsyncSession = Depends(get_session),
) -> MatchListResponse:
    """Return one page of the match archive, newest first by default."""
    matches, total = await matches_service.list_matches(
        session, page=page, page_size=page_size, sort=sort
    )
    return MatchListResponse(
        items=[_match_list_schema(match) for match in matches],
        page=page,
        page_size=page_size,
        total=total,
        pages=page_count(total, page_size),
    )


@router.get("/match", response_model=MatchListSchema)
async def get_match(
    match_id: UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> MatchListSchema:
    """Return one match row (including its ``challenge_id``)."""
    match = await matches_service.get_match(match_id, session)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return _match_list_schema(match)


@router.get("/events", response_model=MatchEventListResponse)
async def list_match_events(
    match_id: UUID = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    sort: Literal["date_asc", "date_desc"] = Query("date_asc"),
    session: AsyncSession = Depends(get_session),
) -> MatchEventListResponse:
    """Return one page of a single match's persisted events, oldest first."""
    if await session.get(Match, match_id) is None:
        raise HTTPException(status_code=404, detail="Match not found")
    events, total = await match_events_service.get_match_events(
        match_id, session, page=page, page_size=page_size, sort=sort
    )
    return MatchEventListResponse(
        items=[MatchEventSchema.model_validate(event) for event in events],
        page=page,
        page_size=page_size,
        total=total,
        pages=page_count(total, page_size),
    )


@router.post(
    "/start-match",
    response_model=StartMatchResponse,
    status_code=202,
)
async def start_match(
    payload: StartMatchRequest,
    session: AsyncSession = Depends(get_session),
) -> StartMatchResponse:
    """Queue a match and return its id immediately.

    The match row is written here with status ``queued`` — the worker flips it
    to ``running`` when it picks the job up and the Engine closes it out as
    ``completed`` or ``failed``, always on that same row.

    The caller can subscribe to ``/spectate?match_id=...`` right away; the
    worker picks the request off the queue and hosts the match.
    """
    challenge = await session.get(Challenge, payload.challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found")

    match_id = uuid4()
    prisoner_provider, prisoner_model = split_model_name(payload.prisoner_model)
    warden_provider, warden_model = split_model_name(payload.warden_model)
    await matches_service.create_queued_match(
        session,
        match_id=match_id,
        challenge_id=payload.challenge_id,
        prisoner_model=prisoner_model,
        prisoner_provider=prisoner_provider,
        warden_model=warden_model,
        warden_provider=warden_provider,
        win_condition=challenge.win_condition,
    )

    message = MatchStartMessage(
        match_id=match_id,
        challenge_id=payload.challenge_id,
        prisoner_model=payload.prisoner_model,
        warden_model=payload.warden_model,
        prisoner_suggestions=payload.prisoner_suggestions,
        warden_suggestions=payload.warden_suggestions,
    )
    try:
        # Celery's client is blocking; keep the request loop free.
        await run_in_threadpool(enqueue_match_start, message)
    except Exception as error:
        logger.exception(f"Failed to enqueue match (challenge {payload.challenge_id})")
        await matches_service.set_status(session, match_id, "failed")
        raise HTTPException(
            status_code=503, detail="Match queue is unavailable"
        ) from error
    logger.info(f"Queued match {match_id} for challenge {payload.challenge_id}")
    return StartMatchResponse(match_id=match_id, status="queued")


@router.post("/spectate")
async def spectate_match(match_id: UUID = Query(...)) -> StreamingResponse:
    """Server-Sent Events stream of one match's events.

    Events are read from the match's Redis pub/sub channel, so several
    spectators can follow the same match and each stream carries the
    ``match_id`` in every payload.
    """
    return StreamingResponse(
        _event_stream(str(match_id)),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


async def _event_stream(match_id: str) -> AsyncIterator[str]:
    yield _sse({"match_id": match_id, "type": "stream_open"})
    try:
        async for payload in subscribe_match_events(match_id):
            if payload is None:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        # Client disconnected; nothing to report.
        raise
    except Exception:
        logger.exception(f"Spectator stream failed for match {match_id}")
        yield _sse({"match_id": match_id, "type": "stream_error"})
        return
    yield _sse({"match_id": match_id, "type": "stream_closed"})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def page_count(total: int, page_size: int) -> int:
    """Number of pages needed to hold ``total`` rows of ``page_size``."""
    if total <= 0:
        return 0
    return (total + page_size - 1) // page_size


def _match_list_schema(match: Match) -> MatchListSchema:
    """Project a match row (plus its challenge name) into the list DTO.

    ``Match.challenge`` is ``lazy="selectin"``, so it is already loaded with
    the row and reading the name costs no extra query.
    """
    return MatchListSchema(
        id=match.id,
        challenge_id=match.challenge_id,
        challenge_name=match.challenge.name if match.challenge is not None else None,
        prisoner_model=match.prisoner_model,
        prisoner_provider=match.prisoner_provider,
        warden_model=match.warden_model,
        warden_provider=match.warden_provider,
        status=match.status,
        winner=match.winner,
        win_condition=match.win_condition,
        duration_seconds=match.duration_seconds,
        started_at=match.started_at,
        finished_at=match.finished_at,
        created_at=match.created_at,
    )
