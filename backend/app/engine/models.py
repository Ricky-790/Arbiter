"""Per-match state models owned by the game engine."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.agents.models import AgentType
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
    credits: int = 50
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
    submitted_flag: str | None = None
    winner: AgentType | None = None
    end_reason: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
