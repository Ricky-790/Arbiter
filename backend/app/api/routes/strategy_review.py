"""The self-improvement loop's HTTP surface: save a strategy, review a match.

Two routers live in this one module because they are two halves of the same
loop. ``reviewer_router`` reads a finished match back so a better approach can
be proposed; ``strategies_router`` promotes the approach a match ran into the
library, from where the next match can be started with it.

They keep their own prefixes rather than sharing one, because they answer
different questions and neither is a sub-resource of the other:

    /api/v1/strategies   the library -- writing to it
    /api/v1/reviewer     one match -- reading it

Both are adapters over services that own their own logic: ``app.db.services``
for the library, ``app.reviewer`` for reading a match back. The review routes in
particular add no filtering, shaping or paging of their own -- the reviewer
decides what a reviewer may see, so that the HTTP surface and the future agent
tools cannot drift apart. Adding a review question means adding a reviewer
function, never a new filter here.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agents_directory import (
    ModelCheckError,
    check_model_exists,
    join_model_name,
)
from app.agents.strategy_reviewer import ReviewRequest, StrategyReviewerAgent
from app.agents.tools.review_tools import ReviewContext
from app.api import sse
from app.api.schemas.dto_models import (
    MatchSide,
    MatchSummaryResponse,
    ReviewStrategyRequest,
    SaveStrategyRequest,
    StrategyDetailResponse,
    StrategyMatchSummary,
    StrategySchema,
)
from app.db import get_session
from app.db.models import EVENT_TYPES, Challenge, Match, Strategy
from app.db.services import matches_service, strategies_service
from app.logger import get_logger
from app.reviewer import service as reviewer
from app.reviewer.models import (
    ConversationEntry,
    MatchEventRecord,
    Page,
    ThoughtRecord,
    ToolCallRecord,
    TrapEvent,
)
from app.reviewer.service import DEFAULT_LIMIT, MAX_LIMIT

logger = get_logger()

strategies_router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])
reviewer_router = APIRouter(prefix="/api/v1/reviewer", tags=["reviewer"])


@strategies_router.post("/save-strategy", response_model=StrategySchema)
async def save_strategy(
    payload: SaveStrategyRequest,
    session: AsyncSession = Depends(get_session),
) -> StrategySchema:
    """Promote one side's strategy out of a match into the library.

    The text comes from the match row, not the request: what gets saved is
    exactly the strategy the match was started with. The saved row's id is then
    written back onto ``matches.strategy_id[user]``, which is how a match says
    which library entry it produced.

    Safe to call twice. ``(match_id, user)`` is unique, so a repeat returns the
    row that already exists instead of inserting a second one -- and the link is
    repaired if it is missing, so a match promoted before its column was written
    can still be fixed by asking again.
    """
    match = await matches_service.get_match(payload.match_id, session)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    existing = await strategies_service.find_for_match(
        payload.match_id, payload.user, session
    )
    if existing is None:
        described = (match.strategy or {}).get(payload.user)
        if not isinstance(described, str) or not described.strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Match {match.id} has no {payload.user} strategy to save; "
                    "it was started without one"
                ),
            )
        stored = await strategies_service.create_for_match(
            session,
            match_id=match.id,
            challenge_id=match.challenge_id,
            user=payload.user,
            strategy=described.strip(),
        )
        logger.info(
            f"Promoted the {payload.user} strategy of match {match.id} "
            f"as strategy {stored.id}"
        )
    else:
        stored = existing

    await matches_service.set_match_strategy_id(
        session, match.id, payload.user, stored.id
    )
    # ``stored.challenge_id`` is the match's, so the parent already in hand
    # knows the name; no second lookup is needed.
    return _strategy_schema(
        stored, match.challenge.name if match.challenge is not None else None
    )


#: Shared query parameters, declared once so the bounds cannot drift apart.
#: ``limit`` is capped at the reviewer's own ceiling, which is also what the
#: reviewer clamps to, so the answer always describes the page that was asked
#: for.
MatchId = Annotated[UUID, Query(description="The match to review.")]
User = Annotated[MatchSide, Query(description="The side to scope this to.")]
#: ``/summary`` is the one route where the side is optional: leaving it out
#: asks for both, which is the whole-match comparison a reviewer usually wants.
OptionalUser = Annotated[
    MatchSide | None,
    Query(description="One side to summarise; omit to get both."),
]
StrategyId = Annotated[UUID, Query(description="The saved strategy to look up.")]
ChallengeId = Annotated[
    UUID | None,
    Query(description="Only strategies played on this challenge; omit for all."),
]
Offset = Annotated[
    int, Query(ge=0, description="Rows to skip; add the returned limit to walk on.")
]
Limit = Annotated[
    int,
    Query(ge=1, le=MAX_LIMIT, description=f"Rows to return, at most {MAX_LIMIT}."),
]


def _page[T](items: list[T], total: int, offset: int, limit: int) -> Page[T]:
    """One slice of a listing, in the shape every other listing uses."""
    return Page(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )


def _strategy_schema(
    strategy: Strategy, challenge_name: str | None
) -> StrategySchema:
    """Project a strategy row plus its challenge's name into the DTO.

    The name is passed in rather than read off the row: it comes from different
    places depending on the query (a join, or a match already loaded), and the
    ORM row carries only ``challenge_id``.
    """
    return StrategySchema(
        id=strategy.id,
        match_id=strategy.match_id,
        challenge_id=strategy.challenge_id,
        challenge_name=challenge_name,
        user=strategy.user,
        one_line_description=strategy.one_line_description,
        strategy=strategy.strategy,
        origin_strat_id=strategy.origin_strat_id,
        created_at=strategy.created_at,
    )


def _match_summary(match: Match) -> StrategyMatchSummary:
    """The compact match a strategy's lineage reports.

    ``Match.challenge`` is ``lazy="selectin"``, so the name is already loaded
    with the row and reading it costs no extra query.
    """
    return StrategyMatchSummary(
        match_id=match.id,
        challenge_name=match.challenge.name if match.challenge is not None else None,
        prisoner_model=match.prisoner_model,
        warden_model=match.warden_model,
        winner=match.winner,
    )


@strategies_router.get("/all", response_model=Page[StrategySchema])
async def list_strategies(
    challenge_id: ChallengeId = None,
    offset: Offset = 0,
    limit: Limit = DEFAULT_LIMIT,
    session: AsyncSession = Depends(get_session),
) -> Page[StrategySchema]:
    """One page of the strategy library, newest first, optionally per challenge.

    Every saved strategy, with its text, the side it is for, the challenge it
    was played on and the match it came from. ``challenge_id`` narrows it to one
    challenge, which is the usual question -- a strategy only means anything
    against the challenge it was played on. An id that matches nothing is an
    empty page, not an error: it is a filter.

    Paged like every other listing: the library grows for as long as matches are
    run, so an unpaged read would get slower and heavier every week.
    """
    rows, total = await strategies_service.list_strategies(
        session, offset=offset, limit=limit, challenge_id=challenge_id
    )
    items = [
        _strategy_schema(row.strategy, row.challenge_name) for row in rows
    ]
    return _page(items, total, offset, limit)


@strategies_router.get("", response_model=StrategyDetailResponse)
async def get_strategy(
    strategy_id: StrategyId,
    offset: Offset = 0,
    limit: Limit = DEFAULT_LIMIT,
    session: AsyncSession = Depends(get_session),
) -> StrategyDetailResponse:
    """One strategy, the match it came from, and where it has since been used.

    ``parent_match`` is the match the strategy was promoted from, so its wording
    can be read against the run that produced it. ``used_in_matches`` is a page
    of the matches started from it, newest first.

    The parent is deliberately *not* in that list, even though promotion writes
    the strategy's id back onto it: the parent ran the wording before the
    strategy existed, so it is the origin, not a use. Leaving it in would put
    the same match in both halves of the lineage.

    Raises:
        HTTPException: 404 if no strategy has that id.
    """
    strategy = await strategies_service.get_strategy_row(strategy_id, session)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    parent = await matches_service.get_match(strategy.strategy.match_id, session)
    used, total = await matches_service.list_matches_using_strategy(
        session,
        strategy_id,
        exclude_match_id=strategy.strategy.match_id,
        offset=offset,
        limit=limit,
    )
    return StrategyDetailResponse(
        strategy=_strategy_schema(strategy.strategy, strategy.challenge_name),
        parent_match=_match_summary(parent) if parent is not None else None,
        used_in_matches=_page(
            [_match_summary(match) for match in used], total, offset, limit
        ),
    )


@reviewer_router.get("/summary", response_model=list[MatchSummaryResponse])
async def get_match_summary(
    match_id: MatchId, user: OptionalUser = None
) -> list[MatchSummaryResponse]:
    """Everything small about one match, for one side or for both.

    The match row (including its challenge and the strategy it ran), the side's
    totals -- credits, tool calls, successes, failures, refusals, and the trap
    counters it owns -- its strategy, and the opening message it was given.

    ``user`` picks a single side, so the reply holds exactly one summary. Omit
    it and both sides come back, Prisoner first: each entry is scoped entirely
    to its own side, so the comparison is two entries of the same shape rather
    than one object with a requested/opponent split. ``match`` is the shared
    match row and carries the full strategy map for context.

    No history: for what was actually said and done, page through
    ``/reviewer/conversation``, ``/tool-calls``, ``/thoughts``, ``/traps`` and
    ``/events``.
    """
    overview = await reviewer.get_match_overview(match_id)
    if overview is None:
        raise HTTPException(status_code=404, detail="Match not found")
    stats = await reviewer.get_match_stats(match_id)
    if stats is None:
        # The match went away between the two reads; it is gone either way.
        raise HTTPException(status_code=404, detail="Match not found")

    sides = {"prisoner": stats.prisoner, "warden": stats.warden}
    wanted: list[MatchSide] = ["prisoner", "warden"] if user is None else [user]

    summaries: list[MatchSummaryResponse] = []
    for side in wanted:
        summaries.append(
            MatchSummaryResponse(
                match=overview,
                user=side,
                stats=sides[side],
                strategy=overview.strategy.get(side),
                triggered_trap_tools=stats.triggered_trap_tools,
                briefing=await reviewer.get_agent_briefing(match_id, side),
            )
        )
    return summaries


@reviewer_router.get("/conversation", response_model=Page[ConversationEntry])
async def get_conversation(
    match_id: MatchId,
    user: User,
    offset: Offset = 0,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[ConversationEntry]:
    """One page of an agent's stored conversation, oldest first.

    This is the long one: the whole model/tool exchange, resolved into one entry
    per step. ``index`` is the position within the whole conversation, so a page
    can be resumed by asking for ``offset + limit``.

    An empty page means that side has no stored conversation -- a match still
    running, or one recorded before conversations were kept.
    """
    await _require_match(match_id)
    return await reviewer.get_conversation(
        match_id, user, offset=offset, limit=limit
    )


@reviewer_router.get("/tool-calls", response_model=Page[ToolCallRecord])
async def get_tool_calls(
    match_id: MatchId,
    user: User,
    success_only: Annotated[
        bool,
        Query(description="Keep only the calls that ran and worked."),
    ] = False,
    offset: Offset = 0,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[ToolCallRecord]:
    """One page of the requested tool calls, oldest first.

    Every request is a row, whatever its outcome: ``success`` is null for a call
    the Engine refused before running, and ``failure_category`` says why. With
    ``success_only`` the filter is applied in the query, so the page and the
    total describe the same set.
    """
    await _require_match(match_id)
    return await reviewer.get_tool_calls(
        match_id, user, offset=offset, limit=limit, success_only=success_only
    )


@reviewer_router.get("/thoughts", response_model=Page[ThoughtRecord])
async def get_thoughts(
    match_id: MatchId,
    user: User,
    offset: Offset = 0,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[ThoughtRecord]:
    """One page of the narration an agent produced for the match log.

    This is what the agent chose to report, not hidden reasoning: Arbiter never
    captures or replays a model's private chain of thought.
    """
    await _require_match(match_id)
    return await reviewer.get_agent_thoughts(
        match_id, user, offset=offset, limit=limit
    )


@reviewer_router.get("/traps", response_model=Page[TrapEvent])
async def get_traps(
    match_id: MatchId,
    offset: Offset = 0,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[TrapEvent]:
    """One page of trap firings, oldest first.

    The detail behind the summary's trap counts: which trap fired, what it was
    watching, and the turn each side was on when it went off. ``target`` is what
    tells two firings of the same trap tool apart.
    """
    await _require_match(match_id)
    return await reviewer.get_trap_events(match_id, offset=offset, limit=limit)


@reviewer_router.get("/events", response_model=Page[MatchEventRecord])
async def get_events(
    match_id: MatchId,
    event_type: Annotated[
        str | None,
        Query(description="Exact event type, e.g. agent_error."),
    ] = None,
    user: Annotated[
        MatchSide | None,
        Query(description="Narrow to one side; omit for both and for system events."),
    ] = None,
    offset: Offset = 0,
    limit: Limit = DEFAULT_LIMIT,
) -> Page[MatchEventRecord]:
    """One page of raw match events, oldest first.

    The catch-all for whatever the shaped listings do not cover: the match's
    start and finish, sandbox events, provider errors and retries.
    """
    if event_type is not None and event_type not in EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown event_type {event_type!r}; known types are "
                f"{', '.join(EVENT_TYPES)}"
            ),
        )
    await _require_match(match_id)
    return await reviewer.get_match_events(
        match_id, event_type=event_type, actor=user, offset=offset, limit=limit
    )


async def _require_match(match_id: UUID) -> None:
    """Reject a listing for a match that does not exist.

    Without this, an unknown id and a match with nothing of that kind both come
    back as an empty page, and a reviewer cannot tell "this match did nothing"
    from "there is no such match".
    """
    if not await reviewer.match_exists(match_id):
        raise HTTPException(status_code=404, detail="Match not found")


def _queue_sink(queue: asyncio.Queue) -> Callable[[str, dict], Awaitable[None]]:
    """An agent event sink that hands events to the streaming generator.

    Progress crosses the thread of control through a queue because the agent
    runs as its own task: the generator has to keep yielding frames while the
    review is still working.
    """

    async def sink(event_type: str, attributes: dict) -> None:
        await queue.put({"type": event_type, **attributes})

    return sink


async def _review_stream(
    agent: StrategyReviewerAgent,
    queue: asyncio.Queue,
    *,
    strategy_id: UUID,
    match_id: UUID,
) -> AsyncIterator[str]:
    """Stream one strategy review, ending with the proposed strategy.

    Emits ``review_started``, then a ``review_tool_call``/``review_tool_result``
    pair per read the agent makes, then exactly one of ``review_finished``
    (carrying the strategy) or ``review_error``. The model's private reasoning
    is never among these -- Arbiter does not capture it. What streams is what
    the review *does*.
    """

    async def run_review() -> None:
        try:
            output = await agent.run_turn()
        except Exception as error:
            logger.exception(f"Strategy review failed for match {match_id}")
            await queue.put({"type": "review_error", "detail": str(error)})
        else:
            if output and output.strip():
                await queue.put(
                    {
                        "type": "review_finished",
                        "strategy_id": str(strategy_id),
                        "match_id": str(match_id),
                        "output": output,
                    }
                )
            else:
                # ``run_turn`` returns None when the turn produced nothing
                # usable, which for a one-shot review is a failure rather than
                # an empty answer.
                await queue.put(
                    {
                        "type": "review_error",
                        "detail": "The reviewer produced no strategy.",
                    }
                )
        finally:
            await queue.put(None)

    task = asyncio.create_task(run_review())
    yield sse.frame(
        {
            "type": "review_started",
            "strategy_id": str(strategy_id),
            "match_id": str(match_id),
        }
    )
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield sse.frame(event)
    finally:
        # Runs on completion *and* on client disconnect, where the generator is
        # cancelled: the review is stopped rather than left running for a reader
        # that has gone away.
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@strategies_router.post("/review")
async def review_strategy(
    payload: ReviewStrategyRequest,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Run the Strategy Reviewer and stream its progress and its answer.

    Reviews one match to propose a better version of one saved strategy. The
    reviewer is an LLM agent with read-only tools over the match, and the model
    and its key are BYOK, named in the body so the credential never reaches a
    URL.

    The response is a Server-Sent Events stream: ``review_tool_call`` and
    ``review_tool_result`` frames as the agent reads, then a single
    ``review_finished`` frame carrying the proposed strategy, or
    ``review_error``. The strategy is returned, never saved -- promoting it is
    a separate, deliberate call to ``/save-strategy``.
    """
    joined = join_model_name(payload.provider, payload.model)
    if joined is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown provider {payload.provider!r}; available providers "
                "are listed by GET /api/v1/matches/models"
            ),
        )
    api_key = payload.api_key.get_secret_value().strip() if payload.api_key else ""
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"Model {payload.provider}:{payload.model} is BYOK; api_key is required",
        )
    # Confirmed before the stream opens, so an unusable key is a plain 400
    # rather than an error frame halfway through a review.
    try:
        await check_model_exists(payload.provider, payload.model, api_key)
    except ModelCheckError as error:
        raise HTTPException(
            status_code=400, detail=f"reviewer: {error.detail}"
        ) from error

    strategy = await strategies_service.get_strategy_row(payload.strategy_id, session)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    match = await matches_service.get_match(payload.match_id, session)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    if strategy.strategy.challenge_id != match.challenge_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Strategy {payload.strategy_id} was played on challenge "
                f"{strategy.strategy.challenge_id}, not {match.challenge_id}"
            ),
        )

    # Columns, not the row: ``Challenge.matches`` is eagerly loaded, so fetching
    # the entity would drag in every match ever played on this challenge.
    challenge = (
        await session.execute(
            select(
                Challenge.name,
                Challenge.description,
                Challenge.win_condition,
                Challenge.prisoner_hint,
                Challenge.warden_hint,
            ).where(Challenge.id == match.challenge_id)
        )
    ).first()
    if challenge is None:
        raise HTTPException(status_code=404, detail="Challenge not found")

    side = strategy.strategy.user
    request = ReviewRequest(
        side=side,
        strategy=strategy.strategy.strategy,
        challenge_name=challenge.name,
        challenge_description=challenge.description,
        win_condition=challenge.win_condition,
        hint=(
            challenge.prisoner_hint if side == "prisoner" else challenge.warden_hint
        ),
    )

    queue: asyncio.Queue = asyncio.Queue()
    agent = StrategyReviewerAgent(
        model_name=joined,
        request=request,
        context=ReviewContext(match_id=match.id),
        api_key=api_key,
        on_event=_queue_sink(queue),
    )
    logger.info(
        f"Reviewing strategy {strategy.strategy.id} against match {match.id} "
        f"for the {side}"
    )
    return StreamingResponse(
        _review_stream(
            agent, queue, strategy_id=strategy.strategy.id, match_id=match.id
        ),
        media_type=sse.SSE_MEDIA_TYPE,
        headers=sse.SSE_HEADERS,
    )
