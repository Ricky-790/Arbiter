"""Read-only access to everything a match review needs.

The reviewer exists so a human or an LLM can propose a better strategy than the
one a match was played with. It **reads and never writes**: no function here
mutates a row, and none takes SQL. A reviewer agent driving these as tools can
only ask the questions defined below, never reach past them into the database.

Every listing is paginated by ``offset``/``limit`` so the frontend and an agent
can both walk it, and each returns the total so a caller knows when to stop.

Kept deliberately as small, single-purpose functions rather than one call that
returns a whole match: an LLM reviewer picks the few it needs, and a page of
tool calls stays cheap to fetch next to a full conversation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session_factory
from app.db.models import Match, MatchAgentMessages, MatchEvent

from .models import (
    AgentBriefing,
    ConversationEntry,
    MatchEventRecord,
    MatchOverview,
    MatchStats,
    Page,
    SideStats,
    ThoughtRecord,
    ToolCallRecord,
    TrapEvent,
)

#: Sides a review can be asked about.
REVIEWABLE_ACTORS = ("prisoner", "warden")

#: Rows returned when a caller does not ask for a size, and the most it may ask
#: for. The ceiling exists so one agent call cannot pull a whole match.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: Persisted event types this module reads by name.
TOOL_CALL_EVENT = "tool_call"
CHAT_EVENT = "chat"
TRAP_TRIGGERED_EVENT = "trap_triggered"

#: Warden tools that arm a trap. Mirrors ``app.engine.traps.TRAP_TOOL_NAMES``;
#: kept as a literal because importing the engine package here would pull the
#: whole runtime into a read-only reviewer. ``test_reviewer`` asserts the two
#: stay equal.
TRAP_TOOL_NAMES = frozenset({"watch_file", "watch_process", "auto_kill"})

#: How the worker marks the strategy inside an agent's opening message. The
#: reviewer reads it back out; see ``_extract_strategy``.
STRATEGY_MARKER = "Try this strategy: "
NO_STRATEGY_MARKER = "No strategy provided"

#: Sections that can follow the strategy in the opening message.
_STRATEGY_END_MARKERS = (
    "\nBriefing:",
    "\nChallenge:",
    "\nWin condition:",
    "\nSubmit your answer",
)


@asynccontextmanager
async def _read_session() -> AsyncIterator[AsyncSession]:
    """One session for one read.

    Nothing here commits: the reviewer has no write path to commit.
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _check_actor(actor: str) -> str:
    """Reject anything that is not a side of a match."""
    if actor not in REVIEWABLE_ACTORS:
        known = ", ".join(REVIEWABLE_ACTORS)
        raise ValueError(f"actor must be one of {known}; got {actor!r}")
    return actor


def _page_bounds(offset: int, limit: int) -> tuple[int, int]:
    """Validate a request's slice, clamping the size to what is allowed."""
    if offset < 0:
        raise ValueError(f"offset must not be negative; got {offset}")
    return offset, max(1, min(limit, MAX_LIMIT))


def _page[T](items: list[T], total: int, offset: int, limit: int) -> Page[T]:
    return Page(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )


async def _count_events(session: AsyncSession, *conditions: Any) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(MatchEvent).where(*conditions)
        )
        or 0
    )


async def _list_events(
    match_id: UUID,
    *,
    event_type: str | None = None,
    actor: str | None = None,
    offset: int,
    limit: int,
) -> tuple[list[MatchEvent], int]:
    """One page of a match's events, oldest first.

    ``id`` breaks ties on ``timestamp`` so paging cannot skip or repeat a row
    when two events share an instant.
    """
    conditions = [MatchEvent.match_id == match_id]
    if event_type is not None:
        conditions.append(MatchEvent.event_type == event_type)
    if actor is not None:
        conditions.append(MatchEvent.actor == _check_actor(actor))

    session_factory = get_session_factory()
    async with session_factory() as session:
        total = await _count_events(session, *conditions)
        rows = (
            (
                await session.execute(
                    select(MatchEvent)
                    .where(*conditions)
                    .order_by(MatchEvent.timestamp.asc(), MatchEvent.id.asc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return list(rows), total


async def get_match_overview(match_id: UUID) -> MatchOverview | None:
    """The match row: who played what, and how it ended.

    ``strategy`` and ``strategy_id`` come straight off the match row, so the
    strategy a review reports is the one the match actually ran, not one parsed
    back out of a prompt.

    Returns ``None`` when no match has that id.
    """
    async with _read_session() as session:
        match = await session.get(Match, match_id)
        if match is None:
            return None
        return MatchOverview(
            match_id=match.id,
            status=match.status,
            winner=match.winner,
            win_condition=match.win_condition,
            challenge_id=match.challenge_id,
            challenge_name=match.challenge.name if match.challenge else None,
            challenge_description=(
                match.challenge.description if match.challenge else None
            ),
            prisoner_provider=match.prisoner_provider,
            prisoner_model=match.prisoner_model,
            warden_provider=match.warden_provider,
            warden_model=match.warden_model,
            strategy=dict(match.strategy or {}),
            strategy_id=dict(match.strategy_id or {}),
            parent_match_id=match.parent_match_id,
            branch_event_id=match.branch_event_id,
            duration_seconds=match.duration_seconds,
            started_at=match.started_at,
            finished_at=match.finished_at,
            created_at=match.created_at,
        )


async def match_exists(match_id: UUID) -> bool:
    """Whether a match with this id exists.

    A listing answers with an empty page both for "no such match" and for "a
    match with nothing of this kind in it", so the API asks this first to tell
    the two apart and 404 the first. It reads only the primary key: a caller
    that wants the row itself uses ``get_match_overview``.
    """
    async with _read_session() as session:
        found = await session.scalar(
            select(Match.id).where(Match.id == match_id).limit(1)
        )
    return found is not None


async def get_match_stats(match_id: UUID) -> MatchStats | None:
    """Both sides' spend and activity, plus the trap activity between them.

    The credit and tool-call totals are the summary the Engine wrote as the
    match closed. The per-tool and success/failure breakdowns are counted from
    ``match_events``, so they are available even for a match that never reached
    its closing write. Returns ``None`` when no match has that id.
    """
    async with _read_session() as session:
        match = await session.get(Match, match_id)
        if match is None:
            return None
        breakdown = await _tool_call_breakdown(session, match_id)
        triggered = await _traps_triggered(session, match_id)

    return MatchStats(
        match_id=match.id,
        prisoner=_side_stats(
            "prisoner",
            match.prisoner_stats,
            breakdown.get("prisoner", _Breakdown()),
            traps_triggered=sum(triggered.values()),
        ),
        warden=_side_stats(
            "warden",
            match.warden_stats,
            breakdown.get("warden", _Breakdown()),
            traps_triggered=sum(triggered.values()),
            traps_armed=_traps_armed(breakdown),
        ),
        triggered_trap_tools=triggered,
    )


class _Breakdown:
    """Running totals for one actor's tool calls."""

    def __init__(self) -> None:
        self.by_name: dict[str, int] = {}
        #: Per tool, the calls that actually ran and worked. A trap only counts
        #: as armed if arming it succeeded: a call the Engine rejected (another
        #: trap already active) never armed anything.
        self.successful_by_name: dict[str, int] = {}
        self.successful = 0
        self.failed = 0
        self.rejected = 0
        self.total = 0


async def _tool_call_breakdown(
    session: AsyncSession, match_id: UUID
) -> dict[str, _Breakdown]:
    """Count a match's tool calls per actor, per tool, and per outcome.

    One grouped query rather than a query per tool: a match can record hundreds
    of calls, and the reviewer asks for these numbers often.
    """
    tool = MatchEvent.action["tool"].astext
    success = MatchEvent.result["success"].astext
    category = MatchEvent.result["failure_category"].astext
    rows = await session.execute(
        select(MatchEvent.actor, tool, success, category, func.count())
        .where(
            MatchEvent.match_id == match_id,
            MatchEvent.event_type == TOOL_CALL_EVENT,
        )
        .group_by(MatchEvent.actor, tool, success, category)
    )

    breakdown: dict[str, _Breakdown] = {}
    for actor, tool_name, succeeded, failure_category, count in rows:
        entry = breakdown.setdefault(actor, _Breakdown())
        entry.total += count
        if tool_name is not None:
            entry.by_name[tool_name] = entry.by_name.get(tool_name, 0) + count
        if failure_category is not None:
            # A rejection never ran, so it is neither a success nor a failure.
            entry.rejected += count
        elif succeeded == "true":
            entry.successful += count
            if tool_name is not None:
                entry.successful_by_name[tool_name] = (
                    entry.successful_by_name.get(tool_name, 0) + count
                )
        else:
            entry.failed += count
    return breakdown


async def _traps_triggered(session: AsyncSession, match_id: UUID) -> dict[str, int]:
    """Which trap tools fired in a match, and how often."""
    trap = MatchEvent.result["trap"].astext
    rows = await session.execute(
        select(trap, func.count())
        .where(
            MatchEvent.match_id == match_id,
            MatchEvent.event_type == TRAP_TRIGGERED_EVENT,
        )
        .group_by(trap)
    )
    return {(trap_name or "unknown"): count for trap_name, count in rows}


def _traps_armed(breakdown: dict[str, _Breakdown]) -> int:
    """How many traps the Warden actually armed.

    Only the Warden arms traps, so only its breakdown counts. Successes are
    counted rather than attempts: a call the Engine rejected (another trap was
    already active) or that failed left no trap behind, and counting it would
    overstate what the Warden did.
    """
    warden = breakdown.get("warden")
    if warden is None:
        return 0
    return sum(
        count
        for tool, count in warden.successful_by_name.items()
        if tool in TRAP_TOOL_NAMES
    )


def _side_stats(
    actor: str,
    stored: dict[str, Any] | None,
    breakdown: _Breakdown,
    *,
    traps_triggered: int,
    traps_armed: int = 0,
) -> SideStats:
    """One side's numbers, preferring the Engine's stored summary.

    The totals the Engine wrote are the record; the event-derived counts are the
    fallback for a match whose summary is missing. Each side is given only the
    trap counts it is judged on, so the other's stay ``None`` rather than
    reading as a real zero.
    """
    summary = stored or {}
    common = {
        "actor": actor,
        "credits_remaining": summary.get("credits"),
        "tool_calls": summary.get("tool_calls"),
        "tool_calls_by_name": dict(sorted(breakdown.by_name.items())),
        "successful_tool_calls": breakdown.successful,
        "failed_tool_calls": breakdown.failed,
        "rejected_tool_calls": breakdown.rejected,
    }
    if actor == "warden":
        return SideStats(
            **common,
            traps_armed=summary.get("traps_armed", traps_armed),
            traps_triggered=summary.get("traps_triggered", traps_triggered),
        )
    return SideStats(
        **common, times_trapped=summary.get("times_trapped", traps_triggered)
    )


async def get_agent_briefing(match_id: UUID, actor: str) -> AgentBriefing | None:
    """The opening message one side was given, and the strategy inside it.

    ``strategy`` is parsed out of the opening message because the strategy is
    not stored on its own. It is ``None`` when the match was played without one,
    or when the message no longer carries the marker it is written with.

    Returns ``None`` when that side has no stored conversation for the match.
    """
    actor = _check_actor(actor)
    async with _read_session() as session:
        stored = await _stored_messages(session, match_id, actor)
    if not stored:
        return None

    briefing = _first_user_prompt(stored)
    if briefing is None:
        return None
    return AgentBriefing(
        actor=actor, strategy=_extract_strategy(briefing), briefing=briefing
    )


def _first_user_prompt(messages: list[dict[str, Any]]) -> str | None:
    """The first thing the agent was told, out of a stored conversation."""
    for message in messages:
        for part in message.get("parts", ()) or ():
            if part.get("part_kind") == "user-prompt":
                content = part.get("content")
                if isinstance(content, str):
                    return content
    return None


def _extract_strategy(briefing: str) -> str | None:
    """Pull the operator's strategy out of an agent's opening message.

    The worker writes it as ``Try this strategy: <text>`` and falls back to
    ``No strategy provided...``. Everything up to the next section is the
    strategy, which keeps a multi-line one intact.
    """
    start = briefing.find(STRATEGY_MARKER)
    if start == -1:
        return None
    rest = briefing[start + len(STRATEGY_MARKER) :]
    if rest.lstrip().startswith(NO_STRATEGY_MARKER):
        return None
    end = len(rest)
    for marker in _STRATEGY_END_MARKERS:
        found = rest.find(marker)
        if found != -1:
            end = min(end, found)
    return rest[:end].strip() or None


async def get_tool_calls(
    match_id: UUID,
    actor: str | None = None,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    success_only: bool = False,
) -> Page[ToolCallRecord]:
    """One page of a match's requested tool calls, oldest first.

    ``actor`` narrows it to one side. ``success_only`` keeps the calls that
    actually ran and worked, which is usually what a review cares about when it
    is looking for what the agent did rather than what it tried.

    Both filters are applied in the query, so the page and the total always
    describe the same set.
    """
    offset, limit = _page_bounds(offset, limit)
    conditions = [
        MatchEvent.match_id == match_id,
        MatchEvent.event_type == TOOL_CALL_EVENT,
    ]
    if actor is not None:
        conditions.append(MatchEvent.actor == _check_actor(actor))
    if success_only:
        conditions.append(MatchEvent.result["success"].astext == "true")

    async with _read_session() as session:
        total = await _count_events(session, *conditions)
        rows = (
            (
                await session.execute(
                    select(MatchEvent)
                    .where(*conditions)
                    .order_by(MatchEvent.timestamp.asc(), MatchEvent.id.asc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return _page([_tool_call_record(row) for row in rows], total, offset, limit)


def _tool_call_record(event: MatchEvent) -> ToolCallRecord:
    result = event.result or {}
    return ToolCallRecord(
        event_id=event.id,
        timestamp=event.timestamp,
        actor=event.actor,
        tool=event.action.get("tool"),
        arguments=event.action.get("arguments") or {},
        success=result.get("success"),
        exit_code=result.get("exit_code"),
        error=result.get("error"),
        failure_category=result.get("failure_category"),
    )


async def get_agent_thoughts(
    match_id: UUID,
    actor: str | None = None,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> Page[ThoughtRecord]:
    """One page of what the agents reported as they worked, oldest first.

    This is the narration an agent chose to produce for the match log, not its
    private reasoning: Arbiter never captures or replays hidden chain of
    thought. ``actor`` narrows it to one side.
    """
    offset, limit = _page_bounds(offset, limit)
    async with _read_session() as session:
        conditions = [
            MatchEvent.match_id == match_id,
            MatchEvent.event_type == CHAT_EVENT,
        ]
        if actor is not None:
            conditions.append(MatchEvent.actor == _check_actor(actor))
        total = await _count_events(session, *conditions)
        rows = (
            (
                await session.execute(
                    select(MatchEvent)
                    .where(*conditions)
                    .order_by(MatchEvent.timestamp.asc(), MatchEvent.id.asc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return _page(
        [
            ThoughtRecord(
                event_id=row.id,
                timestamp=row.timestamp,
                actor=row.actor,
                content=str((row.result or {}).get("content", "")),
            )
            for row in rows
        ],
        total,
        offset,
        limit,
    )


async def get_trap_events(
    match_id: UUID,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> Page[TrapEvent]:
    """One page of trap firings, oldest first.

    A firing is one trap catching the Prisoner, so this is the detail behind
    ``MatchStats.traps_triggered``.
    """
    offset, limit = _page_bounds(offset, limit)
    rows, total = await _list_events(
        match_id, event_type=TRAP_TRIGGERED_EVENT, offset=offset, limit=limit
    )
    return _page(
        [
            TrapEvent(
                event_id=row.id,
                timestamp=row.timestamp,
                trap=(row.result or {}).get("trap"),
                target=(row.result or {}).get("target"),
                prisoner_turn=(row.result or {}).get("prisoner_turn"),
                warden_turn=(row.result or {}).get("warden_turn"),
            )
            for row in rows
        ],
        total,
        offset,
        limit,
    )


async def get_match_events(
    match_id: UUID,
    *,
    event_type: str | None = None,
    actor: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> Page[MatchEventRecord]:
    """One page of raw match events, oldest first.

    The catch-all for anything the shaped listings do not cover -- provider
    errors, the match's start and finish, sandbox events. ``event_type`` and
    ``actor`` are exact-match filters, not free text.
    """
    offset, limit = _page_bounds(offset, limit)
    rows, total = await _list_events(
        match_id, event_type=event_type, actor=actor, offset=offset, limit=limit
    )
    return _page(
        [
            MatchEventRecord(
                event_id=row.id,
                timestamp=row.timestamp,
                actor=row.actor,
                event_type=row.event_type,
                action=row.action or {},
                result=row.result,
            )
            for row in rows
        ],
        total,
        offset,
        limit,
    )


async def get_conversation(
    match_id: UUID,
    actor: str,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> Page[ConversationEntry]:
    """One page of an agent's stored conversation, oldest first.

    The conversation is one JSONB column, so the page is taken in memory: there
    is nothing to push the slice down to. ``index`` is the position within the
    whole conversation, so a caller resumes by asking for ``offset + limit``.

    Returns an empty page when that side has no stored conversation.
    """
    actor = _check_actor(actor)
    offset, limit = _page_bounds(offset, limit)
    async with _read_session() as session:
        stored = await _stored_messages(session, match_id, actor)
    entries = _conversation_entries(stored or [])
    return _page(entries[offset : offset + limit], len(entries), offset, limit)


async def _stored_messages(
    session: AsyncSession, match_id: UUID, actor: str
) -> list[dict[str, Any]] | None:
    result = await session.execute(
        select(MatchAgentMessages.messages).where(
            MatchAgentMessages.match_id == match_id,
            MatchAgentMessages.actor == actor,
        )
    )
    return result.scalar_one_or_none()


def _conversation_entries(messages: list[dict[str, Any]]) -> list[ConversationEntry]:
    """Flatten pydantic-ai's stored message dump into one row per step."""
    entries: list[ConversationEntry] = []
    for message in messages:
        for part in message.get("parts", ()) or ():
            entries.append(_conversation_entry(len(entries), part))
    return entries


def _conversation_entry(index: int, part: dict[str, Any]) -> ConversationEntry:
    kind = str(part.get("part_kind", "unknown"))
    text: str | None = None
    content: dict[str, Any] | None = None

    if kind in {"user-prompt", "system-prompt", "text", "thinking", "retry-prompt"}:
        raw = part.get("content")
        text = raw if isinstance(raw, str) else None
    elif kind == "tool-call":
        args = part.get("args")
        content = args if isinstance(args, dict) else {"args": args}
    elif kind == "tool-return":
        raw = part.get("content")
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, dict):
            content = raw

    return ConversationEntry(
        index=index,
        kind=kind,
        actor=part.get("actor"),
        text=text,
        tool_name=part.get("tool_name"),
        tool_call_id=part.get("tool_call_id"),
        content=content,
    )


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "REVIEWABLE_ACTORS",
    "get_agent_briefing",
    "get_agent_thoughts",
    "get_conversation",
    "get_match_events",
    "get_match_overview",
    "get_match_stats",
    "get_tool_calls",
    "get_trap_events",
    "match_exists",
]
