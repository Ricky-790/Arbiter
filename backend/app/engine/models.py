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


class ForkPlan(BaseModel):
    """How to rebuild one forked match's sandbox before its agents start.

    Produced by ``resumability.plan_fork`` from the source match's persisted
    history: which Solari snapshot to boot (if any) and which calls still have
    to be replayed on top of it.
    """

    source_match_id: UUID
    branch_event_id: UUID
    branch_event_timestamp: datetime
    #: Solari snapshot to boot from; ``None`` means set the challenge up fresh.
    snapshot_id: str | None = None
    #: True when ``snapshot_id`` already reproduces the branch point, so there
    #: is nothing to replay and no new snapshot worth taking.
    snapshot_is_current: bool = False
    #: Calls to replay after the snapshot, in recorded order.
    tool_calls: list[ScriptedToolCall] = Field(default_factory=list)
