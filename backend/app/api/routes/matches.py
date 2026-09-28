"""Match endpoints: queue a match, then spectate its live event stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.agents.agents_directory import (
    PROVIDERS,
    ModelCheckError,
    check_model_exists,
    join_model_name,
    models_for,
)
from app.api.schemas.dto_models import (
    AvailableModelsResponse,
    ForkDetailSchema,
    ForkListResponse,
    ForkMatchRequest,
    ForkSchema,
    MatchEventListResponse,
    MatchEventSchema,
    MatchListResponse,
    MatchListSchema,
    ModelCheckRequest,
    ModelCheckResponse,
    ProviderModels,
    StartForkMatchRequest,
    StartMatchRequest,
    StartMatchResponse,
)
from app.broker.events import subscribe_match_events
from app.broker.models import ForkCreateMessage, MatchStartMessage
from app.broker.queue import enqueue_fork_create, enqueue_match_start
from app.db import get_session
from app.db.models import MATCH_TERMINAL_STATUSES, Challenge, Match
from app.db.services import (
    match_events_service,
    match_forks_service,
    matches_service,
)
from app.db.services.match_fork_service import FAILED as FORK_FAILED
from app.db.services.match_fork_service import READY as FORK_READY
from app.engine.resumability import load_fork_history, snap_branch_event
from app.logger import get_logger
from app.secrets import (
    PRISONER,
    WARDEN,
    ByokStoreError,
    discard_api_keys,
    store_api_key,
)

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


@router.get("/models", response_model=AvailableModelsResponse)
async def list_models() -> AvailableModelsResponse:
    """Return the providers Arbiter can run and the models each one offers.

    The picker chooses a provider first and then a model, so the catalogue is
    nested rather than flattened. Every model is BYOK: the caller must send that
    provider's key for the side using it when starting a match.
    """
    return AvailableModelsResponse(
        providers=[
            ProviderModels(provider=provider, models=models_for(provider))
            for provider in PROVIDERS
        ]
    )


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

    Every model is BYOK, so both sides need a key in this body. The keys are
    written to the encrypted short-lived store and only the match id goes on the
    queue, so no credential is ever part of a queued message or a match row.
    """
    challenge = await session.get(Challenge, payload.challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found")

    # Both sides are confirmed with their providers concurrently: each check is
    # a network round trip, and the two are independent.
    prisoner_key, warden_key = await asyncio.gather(
        _resolve_side(
            payload.prisoner_provider,
            payload.prisoner_model,
            payload.prisoner_api_key,
            "prisoner",
        ),
        _resolve_side(
            payload.warden_provider,
            payload.warden_model,
            payload.warden_api_key,
            "warden",
        ),
    )

    match_id = uuid4()

    # Stored before anything is queued: if the store is unavailable the request
    # fails here rather than leaving a match that can never build its agents.
    try:
        await store_api_key(match_id, PRISONER, prisoner_key)
        await store_api_key(match_id, WARDEN, warden_key)
    except ByokStoreError as error:
        logger.error(f"Provider key store unavailable: {error}")
        raise HTTPException(
            status_code=503, detail="Provider key storage is unavailable"
        ) from error

    await matches_service.create_queued_match(
        session,
        match_id=match_id,
        challenge_id=payload.challenge_id,
        prisoner_model=payload.prisoner_model,
        prisoner_provider=payload.prisoner_provider,
        warden_model=payload.warden_model,
        warden_provider=payload.warden_provider,
        win_condition=challenge.win_condition,
    )

    message = MatchStartMessage(
        match_id=match_id,
        challenge_id=payload.challenge_id,
        prisoner_provider=payload.prisoner_provider,
        prisoner_model=payload.prisoner_model,
        warden_provider=payload.warden_provider,
        warden_model=payload.warden_model,
        prisoner_suggestions=payload.prisoner_suggestions,
        warden_suggestions=payload.warden_suggestions,
    )
    try:
        # Celery's client is blocking; keep the request loop free.
        await run_in_threadpool(enqueue_match_start, message)
    except Exception as error:
        logger.exception(f"Failed to enqueue match (challenge {payload.challenge_id})")
        await _discard_byok_keys(match_id)
        await matches_service.set_status(session, match_id, "failed")
        raise HTTPException(
            status_code=503, detail="Match queue is unavailable"
        ) from error
    logger.info(f"Queued match {match_id} for challenge {payload.challenge_id}")
    return StartMatchResponse(match_id=match_id, status="queued")


@router.post("/fork", response_model=ForkSchema, status_code=202)
async def fork_match(
    payload: ForkMatchRequest,
    session: AsyncSession = Depends(get_session),
) -> ForkSchema:
    """Save a fork point on a finished match.

    A fork is a checkpoint, not a match: it records the match's state at one
    event so a *new* match can be started from it later with whatever models
    and instructions the caller wants. Nothing is hosted here — the fork worker
    rebuilds the state and the fork page starts matches from it.

    The parent must have finished: a match still being hosted is writing its own
    history, so its sandbox state and stored conversation are not yet the point
    a fork would capture. The requested event is snapped forward to the end of
    its model response, so two events of the same turn yield one fork.
    """
    parent = await matches_service.get_match(payload.parent_match_id, session)
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent match not found")
    if parent.status not in MATCH_TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Match {parent.id} is {parent.status}; a fork can only be "
                "created once the match has finished"
            ),
        )

    try:
        event = await snap_branch_event(parent.id, payload.match_event_id, session)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="match_event_id does not belong to parent_match_id",
        ) from error

    fork, created = await match_forks_service.create_pending(
        parent_match_id=parent.id,
        branch_event_id=event.id,
        branch_event_timestamp=event.timestamp,
        session=session,
    )
    if not created and fork.status == FORK_FAILED:
        # Retry rather than hand back a dead fork.
        await match_forks_service.requeue(fork.id, session)
        created = True

    if created:
        message = ForkCreateMessage(
            fork_id=fork.id,
            parent_match_id=parent.id,
            branch_event_id=event.id,
        )
        try:
            # Celery's client is blocking; keep the request loop free.
            await run_in_threadpool(enqueue_fork_create, message)
        except Exception as error:
            logger.exception(f"Failed to enqueue fork of match {parent.id}")
            await match_forks_service.mark_failed(fork.id, session)
            raise HTTPException(
                status_code=503, detail="Fork queue is unavailable"
            ) from error
        logger.info(f"Queued fork {fork.id} of match {parent.id} at event {event.id}")

    stored = await match_forks_service.get_fork(fork.id, session)
    assert stored is not None
    return ForkSchema.model_validate(stored)


@router.get("/forks", response_model=ForkListResponse)
async def list_forks(
    match_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    session: AsyncSession = Depends(get_session),
) -> ForkListResponse:
    """Return saved forks, newest first.

    Omit ``match_id`` for every saved fork — that is the forks tab — or pass it
    to list one match's forks. This is the summary list; the conversations and
    turn history live on ``GET /matches/fork``.
    """
    forks, total = await match_forks_service.list_forks(
        session,
        parent_match_id=match_id,
        page=page,
        page_size=page_size,
    )
    return ForkListResponse(
        items=[ForkSchema.model_validate(fork) for fork in forks],
        page=page,
        page_size=page_size,
        total=total,
        pages=page_count(total, page_size),
    )


@router.get("/fork", response_model=ForkDetailSchema)
async def get_fork(
    fork_id: UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> ForkDetailSchema:
    """Return one saved fork with everything the fork page shows.

    The challenge to start the match on, the parent's models as a starting point
    for the picker, and the history the fork resumes from: the tool calls behind
    the branch point and each agent's conversation up to there.
    """
    fork = await match_forks_service.get_fork(fork_id, session)
    if fork is None:
        raise HTTPException(status_code=404, detail="Fork not found")
    parent = await matches_service.get_match(fork.parent_match_id, session)
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent match not found")

    history = await load_fork_history(
        fork.parent_match_id, fork.branch_event_id, session
    )
    prisoner_messages = (
        fork.prisoner_messages
        if fork.prisoner_messages is not None
        else history.prisoner_messages
    )
    warden_messages = (
        fork.warden_messages
        if fork.warden_messages is not None
        else history.warden_messages
    )

    return ForkDetailSchema(
        id=fork.id,
        parent_match_id=fork.parent_match_id,
        branch_event_id=history.branch_event_id,
        branch_event_timestamp=history.branch_event_timestamp,
        status=fork.status,
        created_at=fork.created_at,
        challenge_id=parent.challenge_id,
        prisoner_provider=parent.prisoner_provider,
        prisoner_model=parent.prisoner_model,
        warden_provider=parent.warden_provider,
        warden_model=parent.warden_model,
        latest_turns=[
            MatchEventSchema.model_validate(event) for event in history.turns
        ],
        prisoner_messages=prisoner_messages,
        warden_messages=warden_messages,
    )


@router.post(
    "/start-from-fork",
    response_model=StartMatchResponse,
    status_code=202,
)
async def start_from_fork(
    payload: StartForkMatchRequest,
    session: AsyncSession = Depends(get_session),
) -> StartMatchResponse:
    """Start a new match from a saved fork.

    The fork supplies the challenge, the sandbox state, and the conversation
    each agent resumes from; the body supplies the models, tips, and keys, so
    the same fork can be run as many different experiments. The new match
    records the fork's branch point as its own lineage, which is what the match
    worker reads to resume it.
    """
    fork = await match_forks_service.get_fork(payload.fork_id, session)
    if fork is None:
        raise HTTPException(status_code=404, detail="Fork not found")
    if fork.status != FORK_READY:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Fork {fork.id} is {fork.status}; it can only be started once "
                "its snapshot is ready"
            ),
        )

    parent = await matches_service.get_match(fork.parent_match_id, session)
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent match not found")

    # Both sides are confirmed with their providers concurrently: each check is
    # a network round trip, and the two are independent.
    prisoner_key, warden_key = await asyncio.gather(
        _resolve_side(
            payload.prisoner_provider,
            payload.prisoner_model,
            payload.prisoner_api_key,
            "prisoner",
        ),
        _resolve_side(
            payload.warden_provider,
            payload.warden_model,
            payload.warden_api_key,
            "warden",
        ),
    )

    match_id = uuid4()

    try:
        await store_api_key(match_id, PRISONER, prisoner_key)
        await store_api_key(match_id, WARDEN, warden_key)
    except ByokStoreError as error:
        logger.error(f"Provider key store unavailable: {error}")
        raise HTTPException(
            status_code=503, detail="Provider key storage is unavailable"
        ) from error

    await matches_service.create_queued_match(
        session,
        match_id=match_id,
        challenge_id=parent.challenge_id,
        prisoner_model=payload.prisoner_model,
        prisoner_provider=payload.prisoner_provider,
        warden_model=payload.warden_model,
        warden_provider=payload.warden_provider,
        win_condition=parent.win_condition,
        # The fork's own branch point, so the match worker knows what to resume.
        parent_match_id=fork.parent_match_id,
        branch_event_id=fork.branch_event_id,
    )

    message = MatchStartMessage(
        match_id=match_id,
        challenge_id=parent.challenge_id,
        prisoner_provider=payload.prisoner_provider,
        prisoner_model=payload.prisoner_model,
        warden_provider=payload.warden_provider,
        warden_model=payload.warden_model,
        prisoner_suggestions=payload.prisoner_suggestions,
        warden_suggestions=payload.warden_suggestions,
    )
    try:
        await run_in_threadpool(enqueue_match_start, message)
    except Exception as error:
        logger.exception(f"Failed to enqueue match from fork {fork.id}")
        await _discard_byok_keys(match_id)
        await matches_service.set_status(session, match_id, "failed")
        raise HTTPException(
            status_code=503, detail="Match queue is unavailable"
        ) from error

    logger.info(f"Queued match {match_id} from fork {fork.id}")
    return StartMatchResponse(match_id=match_id, status="queued")


@router.post("/verify-model", response_model=ModelCheckResponse)
async def verify_model(payload: ModelCheckRequest) -> ModelCheckResponse:
    """Confirm a provider actually serves a model before it is ever queueable.

    The picker lets an operator paste any model name, and the worker claims a
    sandbox before its first model call. Without this check a mistyped name
    would occupy that sandbox and fail with nothing to show, so the answer here
    gates both the UI and ``start-match``.

    A model that cannot be confirmed is reported as ``exists: false`` rather
    than an HTTP error: it is an answer to a question, not a failed request.
    """
    api_key = payload.api_key.get_secret_value().strip()
    if not api_key:
        return ModelCheckResponse(
            exists=False,
            reason="key_rejected",
            detail=(
                f"An API key is required to check {payload.provider} model names"
            ),
        )
    try:
        await check_model_exists(payload.provider, payload.model, api_key)
    except ModelCheckError as error:
        return ModelCheckResponse(
            exists=False, reason=error.reason, detail=error.detail
        )
    return ModelCheckResponse(exists=True)


async def _resolve_side(
    provider: str, model: str, secret: SecretStr | None, side: str
) -> str:
    """Validate one side's provider/model choice and return its API key.

    Raises:
        HTTPException: 400 if the provider is unknown, if no key came with the
            request, or if the provider does not serve the model. Every model is
            BYOK, so the key is always required, and the model is confirmed with
            the provider so an unusable name is rejected before it is queued.
    """
    if join_model_name(provider, model) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown provider {provider!r} for the {side}; available "
                "providers are listed by GET /api/v1/matches/models"
            ),
        )
    key = secret.get_secret_value().strip() if secret is not None else ""
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"Model {provider}:{model} is BYOK; {side}_api_key is required",
        )
    try:
        await check_model_exists(provider, model, key)
    except ModelCheckError as error:
        raise HTTPException(
            status_code=400,
            detail=f"{side}: {error.detail}",
        ) from error
    return key


async def _discard_byok_keys(match_id: UUID) -> None:
    """Best-effort cleanup so a failed request leaves no key behind."""
    try:
        await discard_api_keys(match_id)
    except Exception:
        logger.exception(f"Failed to clear stored BYOK keys for match {match_id}")


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
