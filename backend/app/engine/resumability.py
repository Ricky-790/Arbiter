"""Load persisted match activity as scripted calls, and plan a fork's rebuild."""

from __future__ import annotations

from uuid import UUID

from app.agents.models import AgentType
from app.agents.tools.models import ToolCall
from app.db import get_session_factory
from app.db.models import MatchEvent
from app.db.services import match_events_service, match_snapshots_service
from app.db.services.match_snapshot_service import store_match_snapshot
from app.logger import get_logger

from .models import ForkPlan, ScriptedToolCall

logger = get_logger()

#: ``failure_category`` values a fork does not replay. A trap-blocked call is
#: the only one: trap state is not reconstructed yet, because a trigger lives
#: in a ``sandbox_event`` that a replay does not reproduce deterministically,
#: so re-evaluating the call could let a trap re-arm out of order. Every other
#: refusal *is* replayed on purpose -- with a replayed timestamp clock the
#: Engine reaches the same accept/reject decision the live match did, and
#: re-recording the refusal is what rebuilds the Warden-visible prisoner log.
SKIPPED_TOOL_CALL_CATEGORIES = frozenset({"trap_blocked"})


async def plan_fork(source_match_id: UUID, branch_event_id: UUID) -> ForkPlan:
    """Decide how to rebuild a fork, reusing the newest usable snapshot.

    Prefers, in order:

    1. a snapshot taken exactly at the branch event -- nothing left to replay;
    2. the newest snapshot before it -- only the gap needs replaying;
    3. a fresh challenge setup, replaying the whole history.

    Args:
        source_match_id: the parent match being forked from.
        branch_event_id: the event in that match the fork branches at.

    Raises:
        ValueError: if the branch event does not belong to the source match.
    """
    factory = get_session_factory()
    async with factory() as session:
        branch = await match_events_service.get_match_event(branch_event_id, session)
        if branch is None or branch.match_id != source_match_id:
            raise ValueError(
                f"Match event {branch_event_id} does not belong to match "
                f"{source_match_id}"
            )

        snapshot = await match_snapshots_service.get_snapshot_at_or_before(
            source_match_id, branch.timestamp, branch_event_id, session
        )
        events: list[MatchEvent] | None = None
        if snapshot is not None:
            events = await match_events_service.get_tool_calls_until_event(
                source_match_id,
                branch_event_id,
                session,
                after_event_id=snapshot.branch_event_id,
            )
            if events is None:
                # The snapshot's branch point is not in this match's history.
                # Rebuild from scratch rather than replay the whole match on
                # top of a restored snapshot.
                logger.warning(
                    f"Snapshot for match {source_match_id} at "
                    f"{snapshot.branch_event_id} is unusable; rebuilding"
                )
                snapshot = None

        if snapshot is None:
            events = await match_events_service.get_tool_calls_until_event(
                source_match_id, branch_event_id, session
            )
            if events is None:
                raise ValueError(
                    f"Match event {branch_event_id} does not belong to match "
                    f"{source_match_id}"
                )

    is_current = snapshot is not None and snapshot.branch_event_id == branch_event_id
    return ForkPlan(
        source_match_id=source_match_id,
        branch_event_id=branch_event_id,
        branch_event_timestamp=branch.timestamp,
        snapshot_id=snapshot.solari_snapshot_id if snapshot is not None else None,
        snapshot_is_current=is_current,
        tool_calls=[] if is_current else _to_calls(events),
    )


async def get_scripted_calls(
    source_match_id: UUID,
    branch_event_id: UUID,
    *,
    after_event_id: UUID | None = None,
) -> list[ScriptedToolCall]:
    """Return actor-aware tool calls from a match through its branch event.

    ``source_match_id`` is the match being forked *from* -- the parent, not the
    fork being created -- and the window stops at and includes
    ``branch_event_id``. ``after_event_id`` bounds it from below, exclusively,
    for rebooting from a snapshot. Calls in
    :data:`SKIPPED_TOOL_CALL_CATEGORIES` are left out; every other refusal is
    included so the replay reproduces the refusal (and the prisoner-log entry
    it wrote).

    Raises:
        ValueError: if the branch event does not belong to the source match.
    """
    factory = get_session_factory()
    async with factory() as session:
        events = await match_events_service.get_tool_calls_until_event(
            source_match_id,
            branch_event_id,
            session,
            after_event_id=after_event_id,
        )
    if events is None:
        raise ValueError(
            f"Match event {branch_event_id} does not belong to match "
            f"{source_match_id}"
        )
    return _to_calls(events)


async def store_fork_snapshot(fork: ForkPlan, solari_snapshot_id: str) -> None:
    """Index the snapshot a rebuild just captured, so a later fork is cheap.

    Best-effort by design: losing the index only means the next fork of this
    point replays again.
    """
    await store_match_snapshot(
        match_id=fork.source_match_id,
        branch_event_id=fork.branch_event_id,
        branch_event_timestamp=fork.branch_event_timestamp,
        solari_snapshot_id=solari_snapshot_id,
    )


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
