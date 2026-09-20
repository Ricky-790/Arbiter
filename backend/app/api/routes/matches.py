"""Match endpoints: queue a match, then spectate its live event stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.schemas.dto_models import StartMatchRequest, StartMatchResponse
from app.broker.events import subscribe_match_events
from app.broker.models import MatchStartMessage
from app.broker.queue import enqueue_match_start
from app.logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/matches", tags=["matches"])

SSE_MEDIA_TYPE = "text/event-stream"

#: Comments keep proxies from closing an idle SSE connection.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/free-models")
async def list_free_models() -> dict:
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post(
    "/start-match",
    response_model=StartMatchResponse,
    status_code=202,
)
async def start_match(payload: StartMatchRequest) -> StartMatchResponse:
    """Queue a match and return its id immediately.

    The caller can subscribe to ``/spectate?match_id=...`` right away; the
    worker picks the request off the queue and hosts the match.
    """
    match_id = uuid4()
    message = MatchStartMessage(
        match_id=match_id,
        challenge_id=payload.challenge_id,
        prisoner_model=payload.prisoner_model,
        warden_model=payload.warden_model,
    )
    try:
        # Celery's client is blocking; keep the request loop free.
        await run_in_threadpool(enqueue_match_start, message)
    except Exception as error:
        logger.exception(f"Failed to enqueue match (challenge {payload.challenge_id})")
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
