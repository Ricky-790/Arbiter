"""Per-match state models owned by the game engine."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.models import AgentType
from app.agents.tools import ToolCall
from app.agents.tools.models import ToolResult
from app.sandbox.models import ChallengeSpec


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MatchStatus(str, Enum):
    CREATED = "created"
    SETTING_UP = "setting_up"
    RUNNING = "running"
    FINISHED = "finished"
    ERROR = "error"


class AgentState(BaseModel):
    credits: int = 100
    cooldown_until: datetime | None = None
    reaction_until: datetime | None = None
    last_result: ToolResult | None = None
    #: Actions this side requested. Counted on every call that reaches the
    #: Engine, rejected ones included, so it matches the ``tool_call`` rows in
    #: ``match_events``. Replayed calls from a fork rebuild are not counted --
    #: they are history being restored, not new actions.
    tool_calls: int = 0
    #: Completed model cycles for this side: one per ``run_turn``. Recorded on a
    #: trap firing so the reviewer can say which turn it happened on. A trap
    #: fires from a sandbox observation rather than from a tool call, so this is
    #: the turn that was in progress, not the action that caused it.
    turns: int = 0
    #: Warden: traps it armed. Only successful armings count -- a call the Engine
    #: rejected left no trap behind.
    traps_armed: int = 0
    #: Warden: traps of its own that fired on the Prisoner.
    traps_triggered: int = 0
    #: Prisoner: how many times a trap caught it. The same firing increments the
    #: Warden's ``traps_triggered``; each side keeps the count it is judged on.
    times_trapped: int = 0


class ActiveTrap(BaseModel):
    tool_name: str
    target: str
    armed_at: datetime = Field(default_factory=utc_now)


class MatchState(BaseModel):
    match_id: str
    challenge: ChallengeSpec
    status: MatchStatus = MatchStatus.CREATED
    prisoner: AgentState = Field(default_factory=AgentState)
    warden: AgentState = Field(default_factory=AgentState)
    active_trap: ActiveTrap | None = None
    # Immediately after a trigger, this trap cannot be armed as the Warden's
    # next action. It is cleared after any other successful Warden action.
    blocked_trap_name: str | None = None
    submitted_flag: dict[str, Any] | None = None
    winner: AgentType | None = None
    end_reason: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class ScriptedToolCall(BaseModel):
    tool: ToolCall
    timestamp: datetime
    actor: AgentType


class ForkBuildPlan(BaseModel):
    """How to rebuild one fork's sandbox.

    ``base_snapshot_id`` is the closest state that is already rebuilt -- an
    earlier fork of the same match, or the fork this match itself started from
    -- so only ``tool_calls`` have to be replayed on top of it. ``None`` means
    the challenge is set up fresh first.
    """

    branch_event_id: UUID
    branch_event_timestamp: datetime
    base_snapshot_id: str | None = None
    #: Calls to replay after the base, in recorded order.
    tool_calls: list[ScriptedToolCall] = Field(default_factory=list)


class ForkPlan(BaseModel):
    """What a forked match needs once its snapshot exists.

    Produced by ``resumability.plan_resume``: the snapshot to boot and the
    conversation each agent resumes from. Rebuilding the sandbox is deliberately
    not part of this -- the fork worker already did that.
    """

    source_match_id: UUID
    branch_event_id: UUID
    branch_event_timestamp: datetime
    #: Solari snapshot that already reproduces the branch point.
    snapshot_id: str
    #: Each agent's conversation as of the branch point, ready to seed the
    #: fork's agents. ``None`` when the parent stored no history, in which case
    #: that agent starts blank.
    prisoner_messages: list[dict[str, Any]] | None = None
    warden_messages: list[dict[str, Any]] | None = None
