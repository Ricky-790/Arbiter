"""Match endpoints: queue a match, then spectate its live event stream."""

from __future__ import annotations

import asyncio
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
from app.api import sse
from app.api.api_keys import decrypt_api_key
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
    strategies_service,
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

#: Events returned per page by the paginated list endpoints.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


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
    """Return one page of a single match's persisted events, oldest first.

    ``result`` is served as stored. For a ``tool_call`` row that includes the
    acting side's remaining ``credits`` after the call -- attached by the
    Engine when it built the same ``ToolResult`` the agent read -- so a caller
    can follow the economy through the match without recomputing it.
    """
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

    # Resolved before any key is stored or queued, so an unusable strategy id
    # fails the request outright instead of leaving a match behind.
    strategy = await _resolve_strategies(
        session,
        challenge_id=payload.challenge_id,
        prisoner_strategy_id=payload.prisoner_strategy_id,
        prisoner_suggestions=payload.prisoner_suggestions,
        warden_strategy_id=payload.warden_strategy_id,
        warden_suggestions=payload.warden_suggestions,
    )

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
        # The first side may already have landed when the second failed, and no
        # match row exists to ever redeem it, so take both back now rather than
        # leaving a credential in Redis for the TTL.
        await _discard_byok_keys(match_id)
        logger.error(f"Provider key store unavailable: {error}")
        raise HTTPException(
            status_code=503, detail="Provider key storage is unavailable"
        ) from error

    try:
        await matches_service.create_queued_match(
            session,
            match_id=match_id,
            challenge_id=payload.challenge_id,
            prisoner_model=payload.prisoner_model,
            prisoner_provider=payload.prisoner_provider,
            warden_model=payload.warden_model,
            warden_provider=payload.warden_provider,
            win_condition=challenge.win_condition,
            strategy=strategy,
            strategy_id=_named_strategy_ids(
                payload.prisoner_strategy_id, payload.warden_strategy_id
            ),
        )
    except Exception:
        # No row was written, so nothing will ever redeem these keys.
        await _discard_byok_keys(match_id)
        raise

    message = MatchStartMessage(
        match_id=match_id,
        challenge_id=payload.challenge_id,
        prisoner_provider=payload.prisoner_provider,
        prisoner_model=payload.prisoner_model,
        warden_provider=payload.warden_provider,
        warden_model=payload.warden_model,
        prisoner_suggestions=strategy.get("prisoner"),
        warden_suggestions=strategy.get("warden"),
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
                f"Fork {fork.id} is {fork.status}; it can only be started once its snapshot is ready"
            ),
        )

    parent = await matches_service.get_match(fork.parent_match_id, session)
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent match not found")

    # Resolved against the parent's challenge: a fork stays on that challenge, so
    # a strategy from a different one is not usable here.
    strategy = await _resolve_strategies(
        session,
        challenge_id=parent.challenge_id,
        prisoner_strategy_id=payload.prisoner_strategy_id,
        prisoner_suggestions=payload.prisoner_suggestions,
        warden_strategy_id=payload.warden_strategy_id,
        warden_suggestions=payload.warden_suggestions,
    )

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
        # Same as the start route: a half-stored pair has no match to redeem it.
        await _discard_byok_keys(match_id)
        logger.error(f"Provider key store unavailable: {error}")
        raise HTTPException(
            status_code=503, detail="Provider key storage is unavailable"
        ) from error

    try:
        await matches_service.create_queued_match(
            session,
            match_id=match_id,
            challenge_id=parent.challenge_id,
            prisoner_model=payload.prisoner_model,
            prisoner_provider=payload.prisoner_provider,
            warden_model=payload.warden_model,
            warden_provider=payload.warden_provider,
            win_condition=parent.win_condition,
            strategy=strategy,
            strategy_id=_named_strategy_ids(
                payload.prisoner_strategy_id, payload.warden_strategy_id
            ),
            # The fork's own branch point, so the match worker knows what to resume.
            parent_match_id=fork.parent_match_id,
            branch_event_id=fork.branch_event_id,
        )
    except Exception:
        # No row was written, so nothing will ever redeem these keys.
        await _discard_byok_keys(match_id)
        raise

    message = MatchStartMessage(
        match_id=match_id,
        challenge_id=parent.challenge_id,
        prisoner_provider=payload.prisoner_provider,
        prisoner_model=payload.prisoner_model,
        warden_provider=payload.warden_provider,
        warden_model=payload.warden_model,
        prisoner_suggestions=strategy.get("prisoner"),
        warden_suggestions=strategy.get("warden"),
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
    api_key = (decrypt_api_key(payload.api_key, field="api_key") or "").strip()
    if not api_key:
        return ModelCheckResponse(
            exists=False,
            reason="key_rejected",
            detail=(f"An API key is required to check {payload.provider} model names"),
        )
    try:
        await check_model_exists(payload.provider, payload.model, api_key)
    except ModelCheckError as error:
        return ModelCheckResponse(
            exists=False, reason=error.reason, detail=error.detail
        )
    return ModelCheckResponse(exists=True)


def _named_strategy_ids(
    prisoner_strategy_id: UUID | None, warden_strategy_id: UUID | None
) -> dict[str, str]:
    """The library ids a start request named, keyed by side, as JSONB strings.

    Recorded on the new match so a saved strategy can be traced to every match
    that ran it. Without this the id only ever pointed the other way -- from a
    match to the strategy it produced -- and "which matches used this strategy"
    would have nothing to read.

    Only ids that were actually supplied appear; a side started from free text
    has no library row to name.
    """
    return {
        side: str(strategy_id)
        for side, strategy_id in (
            ("prisoner", prisoner_strategy_id),
            ("warden", warden_strategy_id),
        )
        if strategy_id is not None
    }


async def _resolve_strategies(
    session: AsyncSession,
    *,
    challenge_id: UUID,
    prisoner_strategy_id: UUID | None,
    prisoner_suggestions: str | None,
    warden_strategy_id: UUID | None,
    warden_suggestions: str | None,
) -> dict[str, str]:
    """Work out the strategy each side is started with.

    A side given a ``*_strategy_id`` is started from that library strategy, and
    the id wins over any free-text suggestions sent alongside it -- the explicit
    reference is the more specific request. A side without one is started from
    its suggestions, if it has any.

    The result is keyed by side and omits sides with no strategy, so an empty
    mapping means neither side got one. It is written to the match row *and*
    sent to the worker as that side's suggestions, so what is fed to the agent
    and what is later promoted to the library are the same text.

    Raises:
        HTTPException: 404 if a referenced strategy does not exist, or 400 if it
            belongs to a different challenge -- a strategy is only meaningful
            against the challenge it was played on.
    """
    requested = {"prisoner": prisoner_strategy_id, "warden": warden_strategy_id}
    stored_by_id = await strategies_service.get_strategies(
        [one for one in requested.values() if one is not None], session
    )
    supplied = {"prisoner": prisoner_suggestions, "warden": warden_suggestions}

    resolved: dict[str, str] = {}
    for side, strategy_id in requested.items():
        if strategy_id is None:
            text = supplied[side]
            if text is not None and text.strip():
                resolved[side] = text.strip()
            continue
        stored = stored_by_id.get(strategy_id)
        if stored is None:
            raise HTTPException(
                status_code=404, detail=f"Strategy {strategy_id} not found"
            )
        if stored.challenge_id != challenge_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Strategy {strategy_id} was played on challenge "
                    f"{stored.challenge_id}, not {challenge_id}"
                ),
            )
        resolved[side] = stored.strategy
    return resolved


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
    key = (decrypt_api_key(secret, field=f"{side}_api_key") or "").strip()
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
        media_type=sse.SSE_MEDIA_TYPE,
        headers=sse.SSE_HEADERS,
    )


async def _event_stream(match_id: str) -> AsyncIterator[str]:
    yield sse.frame({"match_id": match_id, "type": "stream_open"})
    try:
        async for payload in subscribe_match_events(match_id):
            if payload is None:
                yield sse.keep_alive()
                continue
            yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        # Client disconnected; nothing to report.
        raise
    except Exception:
        logger.exception(f"Spectator stream failed for match {match_id}")
        yield sse.frame({"match_id": match_id, "type": "stream_error"})
        return
    yield sse.frame({"match_id": match_id, "type": "stream_closed"})


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
