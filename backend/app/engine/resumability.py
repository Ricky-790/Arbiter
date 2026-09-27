"""Plan fork work from persisted match history.

Three callers read the same history for different reasons:

* ``POST /matches/fork`` registers a fork, and the **fork worker** then calls
  :func:`plan_fork_build` to learn what it has to replay. The worker rebuilds
  the sandbox itself and stores the snapshot and conversations on the fork.
* the **fork page** calls :func:`load_fork_history` for the turns and
  conversations a saved fork resumes from.
* the **match worker** calls :func:`plan_resume` when it hosts a match that was
  started from a fork.

Nothing here replays a tool call. This module only reads the database and
slices history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple
from uuid import UUID

from pydantic_ai.messages import ModelMessagesTypeAdapter, ToolReturnPart
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentType
from app.agents.tools.models import ToolCall
from app.db import get_session_factory
from app.db.models import MatchEvent
from app.db.services import (
    match_agent_messages_service,
    match_events_service,
    match_forks_service,
    matches_service,
)
from app.logger import get_logger

from .models import ForkBuildPlan, ForkPlan, ScriptedToolCall

logger = get_logger()

#: ``failure_category`` values a fork does not replay. A trap-blocked call is
#: the only one: trap state is not reconstructed yet, because a trigger lives
#: in a ``sandbox_event`` that a replay does not reproduce deterministically,
#: so re-evaluating the call could let a trap re-arm out of order. Every other
#: refusal *is* replayed on purpose -- with a replayed timestamp clock the
#: Engine reaches the same accept/reject decision the live match did, and
#: re-recording the refusal is what rebuilds the Warden-visible prisoner log.
SKIPPED_TOOL_CALL_CATEGORIES = frozenset({"trap_blocked"})


class ForkNotReadyError(RuntimeError):
    """The snapshot a match was started from has not been built yet."""


class ForkHistory(NamedTuple):
    """What a fork resumes from at one branch point.

    ``turns`` is the sequence of tool calls replayed to rebuild the sandbox at
    that point; the two conversations are each agent's history cut at the same
    instant.
    """

    branch_event_id: UUID
    branch_event_timestamp: datetime
    turns: list[MatchEvent]
    prisoner_messages: list[dict[str, Any]] | None
    warden_messages: list[dict[str, Any]] | None


async def plan_fork_build(
    match_id: UUID, branch_event_id: UUID
) -> ForkBuildPlan:
    """Decide what the fork worker has to replay to reach one branch point.

    ``match_id`` is the match being forked. The base is the newest *ready* fork
    of that match at or before the point; when there is none it is the fork the
    match itself was started from. That is what makes forking a forked match
    cheap: only the match's own calls are replayed, not the whole ancestry.

    Raises:
        ValueError: if the branch event does not belong to the match.
    """
    factory = get_session_factory()
    async with factory() as session:
        event = await snap_branch_event(match_id, branch_event_id, session)

        cached = await match_forks_service.get_ready_at_or_before(
            match_id, event.timestamp, event.id, session
        )
        if cached is not None:
            base_snapshot_id = cached.solari_snapshot_id
            # The base snapshot was taken at the end of its batch, so bound the
            # replay there as well: a fork row recorded before snapping existed
            # would otherwise replay its own siblings a second time on top of a
            # snapshot that already contains them.
            after = await snap_branch_event(
                match_id, cached.branch_event_id, session
            )
            after_event_id: UUID | None = after.id
        else:
            base_snapshot_id = await _origin_snapshot(match_id, session)
            after_event_id = None

        events = await match_events_service.get_tool_calls_until_event(
            match_id, event.id, session, after_event_id=after_event_id
        )

    return ForkBuildPlan(
        branch_event_id=event.id,
        branch_event_timestamp=event.timestamp,
        base_snapshot_id=base_snapshot_id,
        tool_calls=_to_calls(events or []),
    )


async def plan_resume(match_id: UUID) -> ForkPlan:
    """Return what a match started from a fork needs in order to run.

    A match records the fork point it resumed from as ``parent_match_id`` and
    ``branch_event_id``; the fork at that point holds the snapshot to boot and
    the conversations to seed.

    Raises:
        ValueError: if the match does not exist or was not started from a fork.
        ForkNotReadyError: if the fork's snapshot was never built.
    """
    factory = get_session_factory()
    async with factory() as session:
        match = await matches_service.get_match(match_id, session)
        if match is None:
            raise ValueError(f"Match {match_id} does not exist")
        if match.parent_match_id is None or match.branch_event_id is None:
            raise ValueError(f"Match {match_id} was not started from a fork")

        fork = await match_forks_service.get_by_point(
            match.parent_match_id, match.branch_event_id, session
        )
        if fork is None or fork.solari_snapshot_id is None:
            raise ForkNotReadyError(
                f"Fork for match {match_id} at event {match.branch_event_id} "
                "has no snapshot"
            )

        prisoner_messages = fork.prisoner_messages
        warden_messages = fork.warden_messages
        if prisoner_messages is None and warden_messages is None:
            # Recorded before forks stored their own conversations; the parent
            # still has the history to cut.
            history = await load_fork_history(
                fork.parent_match_id, fork.branch_event_id, session
            )
            prisoner_messages = history.prisoner_messages
            warden_messages = history.warden_messages

        return ForkPlan(
            source_match_id=fork.parent_match_id,
            branch_event_id=fork.branch_event_id,
            branch_event_timestamp=fork.branch_event_timestamp,
            snapshot_id=fork.solari_snapshot_id,
            prisoner_messages=prisoner_messages,
            warden_messages=warden_messages,
        )


async def load_fork_history(
    source_match_id: UUID,
    branch_event_id: UUID,
    session: AsyncSession,
) -> ForkHistory:
    """Return the turns and conversations a fork at this point resumes from.

    The branch event is snapped to the end of its model response first, so the
    history stops where the agents could actually have been.

    Raises:
        ValueError: if the branch event does not belong to the source match.
    """
    event = await snap_branch_event(source_match_id, branch_event_id, session)
    turns = (
        await match_events_service.get_tool_calls_until_event(
            source_match_id, event.id, session
        )
        or []
    )
    prisoner_messages = await _load_cut_history(
        match_id=source_match_id,
        actor=AgentType.PRISONER,
        prefix=turns,
        session=session,
    )
    warden_messages = await _load_cut_history(
        match_id=source_match_id,
        actor=AgentType.WARDEN,
        prefix=turns,
        session=session,
    )
    return ForkHistory(
        branch_event_id=event.id,
        branch_event_timestamp=event.timestamp,
        turns=turns,
        prisoner_messages=prisoner_messages,
        warden_messages=warden_messages,
    )


async def snap_branch_event(
    match_id: UUID, branch_event_id: UUID, session: AsyncSession
) -> MatchEvent:
    """Load one event and snap it forward to its model response's last call.

    Pydantic AI returns every tool result from one response in a single
    message, so no conversation state exists between two calls of the same
    response. A fork there would hand the agents a history whose returns they
    never earned while the environment sat behind it; snapping forward to the
    batch's last call keeps the two in step.

    Events recorded before batches were tracked have no ``batch_id`` and are
    used as they are.

    Raises:
        ValueError: if the event does not belong to the match.
    """
    event = await match_events_service.get_match_event(branch_event_id, session)
    if event is None or event.match_id != match_id:
        raise ValueError(
            f"Match event {branch_event_id} does not belong to match {match_id}"
        )
    batch_id = (event.action or {}).get("batch_id")
    if not isinstance(batch_id, str):
        return event
    end = await match_events_service.get_batch_end(match_id, batch_id, session)
    return end if end is not None else event


async def _origin_snapshot(match_id: UUID, session: AsyncSession) -> str | None:
    """The snapshot this match was started from, if it began at a fork.

    A match started from a fork is already sitting on that fork's state, so a
    fork of *it* only has to replay this match's own calls on top.
    """
    match = await matches_service.get_match(match_id, session)
    if (
        match is None
        or match.parent_match_id is None
        or match.branch_event_id is None
    ):
        return None
    origin = await match_forks_service.get_by_point(
        match.parent_match_id, match.branch_event_id, session
    )
    return origin.solari_snapshot_id if origin is not None else None


async def _load_cut_history(
    *,
    match_id: UUID,
    actor: AgentType,
    prefix: list[MatchEvent],
    session: AsyncSession,
) -> list[dict[str, Any]] | None:
    """Load one agent's stored conversation, cut at the branch point."""
    stored = await match_agent_messages_service.get_messages(
        match_id, actor.value, session
    )
    if not stored:
        return None
    return _cut_history(stored, _tool_call_ids(prefix))


def _tool_call_ids(events: list[MatchEvent]) -> set[str]:
    """Every native tool-call id a fork replays or has already rebuilt."""
    ids: set[str] = set()
    for event in events:
        tool_call_id = (event.action or {}).get("tool_call_id")
        if isinstance(tool_call_id, str):
            ids.add(tool_call_id)
    return ids


def _cut_history(
    messages: list[dict[str, Any]], replayed_ids: set[str]
) -> list[dict[str, Any]] | None:
    """Return the prefix of a conversation that ends at the branch point.

    The history is only ever *sliced*, never rewritten: the cut is the last
    tool-return message whose returns are all inside the replayed prefix, which
    is exactly the last fully resolved model response. Everything after it
    belongs to the part of the parent match the fork is re-deciding.

    Returns ``None`` when nothing had been resolved yet, leaving that agent
    with a blank history rather than a half-turn.
    """
    typed = ModelMessagesTypeAdapter.validate_python(messages)
    cut: int | None = None
    for index, message in enumerate(typed):
        returns = [
            part
            for part in getattr(message, "parts", ())
            if isinstance(part, ToolReturnPart)
        ]
        if returns and all(part.tool_call_id in replayed_ids for part in returns):
            cut = index
    if cut is None:
        return None
    return ModelMessagesTypeAdapter.dump_python(typed[: cut + 1], mode="json")


def _to_calls(events: list[MatchEvent]) -> list[ScriptedToolCall]:
    return [_scripted_call(event) for event in events if not _is_skipped(event)]


def _is_skipped(event: MatchEvent) -> bool:
    """Whether this call is one a replay deliberately leaves out."""
    result = event.result or {}
    return result.get("failure_category") in SKIPPED_TOOL_CALL_CATEGORIES


def _scripted_call(event: MatchEvent) -> ScriptedToolCall:
    """Translate one persisted ``tool_call`` row into a replayable call."""
    action = event.action
    tool_name = action.get("tool")
    arguments = action.get("arguments", {})
    if not isinstance(tool_name, str) or not isinstance(arguments, dict):
        raise ValueError(f"Invalid tool_call action in event {event.id}")
    try:
        actor = AgentType(event.actor)
    except ValueError as error:
        raise ValueError(f"Invalid actor in event {event.id}") from error
    return ScriptedToolCall(
        tool=ToolCall(name=tool_name, arguments=arguments),
        timestamp=event.timestamp,
        actor=actor,
    )
