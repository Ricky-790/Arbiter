"""Data shapes the reviewer returns.

Plain read models: every field is derived from a table the match runtime already
owns, and none of them is written back.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    """One slice of a longer listing.

    Every listing is paginated so the frontend and an agent can both walk it:
    ``has_more`` says whether asking again with ``offset + limit`` returns
    anything, without a second call to find out.
    """

    items: list[T]
    total: int
    offset: int
    limit: int
    has_more: bool


class MatchOverview(BaseModel):
    """The match row itself: who played what, and how it ended."""

    match_id: UUID
    status: str
    winner: str | None
    win_condition: str
    challenge_id: UUID
    challenge_name: str | None
    #: The challenge's own description, so a review does not need a second read
    #: to know what was being played.
    challenge_description: str | None = None
    prisoner_provider: str
    prisoner_model: str
    warden_provider: str
    warden_model: str
    #: The strategy each side was started with, keyed by side, straight off the
    #: match row. Unlike ``AgentBriefing.strategy`` this is not parsed out of a
    #: prompt, so it is the authoritative record of what the match ran with.
    strategy: dict[str, str] = Field(default_factory=dict)
    #: ``strategies.id`` per side, once a side's strategy has been promoted into
    #: the library. Empty until then.
    strategy_id: dict[str, str] = Field(default_factory=dict)
    #: Set when this match was started from a fork: the match it branched from.
    parent_match_id: UUID | None
    branch_event_id: UUID | None
    duration_seconds: float | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class SideStats(BaseModel):
    """What one side spent and did.

    ``credits_remaining`` and ``tool_calls`` come from the summary the Engine
    wrote as the match closed; both are ``None`` for a match recorded before
    that summary existed, or for one that never reached its closing write. The
    breakdown fields are counted from ``match_events`` instead, so they are
    always available.
    """

    actor: str
    credits_remaining: int | None
    tool_calls: int | None
    tool_calls_by_name: dict[str, int] = Field(default_factory=dict)
    successful_tool_calls: int
    failed_tool_calls: int
    #: Actions the Engine refused before running them (cooldown, credits,
    #: trap constraints). Counted separately because a refused action is a
    #: distinct outcome from a failed one.
    rejected_tool_calls: int
    #: Prisoner only: how many times a trap caught it. ``None`` for the Warden,
    #: which is not caught by anything.
    times_trapped: int | None = None
    #: Warden only: traps it armed. ``None`` for the Prisoner, which arms none.
    traps_armed: int | None = None
    #: Warden only: traps of its own that fired on the Prisoner. ``None`` for
    #: the Prisoner; its side of the same event is ``times_trapped``.
    traps_triggered: int | None = None


class MatchStats(BaseModel):
    """Both sides' numbers, plus the trap activity between them.

    The per-side counts come from the summary the Engine wrote at the end of the
    match, and fall back to being counted from ``match_events`` when that
    summary is missing (a match recorded before the columns existed, or one that
    never reached its closing write).
    """

    match_id: UUID
    prisoner: SideStats
    warden: SideStats
    #: Which trap tool fired, and how often -- the "which traps" detail behind
    #: the per-side counts. Always counted from events, because it is a
    #: breakdown rather than a total.
    triggered_trap_tools: dict[str, int] = Field(default_factory=dict)


class AgentBriefing(BaseModel):
    """The opening message an agent was given for this match."""

    actor: str
    #: The operator's strategy, when the briefing carried one. Parsed out of
    #: the prompt, so it is ``None`` for a match played without one.
    strategy: str | None
    #: The whole opening message, strategy and challenge hint included.
    briefing: str


class ToolCallRecord(BaseModel):
    """One requested tool call, whatever its outcome."""

    event_id: UUID
    timestamp: datetime
    actor: str
    tool: str | None
    arguments: dict[str, Any]
    success: bool | None
    exit_code: int | None
    error: str | None
    #: Why the Engine refused or skipped it, when it did.
    failure_category: str | None


class ThoughtRecord(BaseModel):
    """One piece of narration an agent produced for the match log.

    This is what the agent chose to report, not hidden reasoning: Arbiter never
    captures or replays a model's private chain of thought.
    """

    event_id: UUID
    timestamp: datetime
    actor: str
    content: str


class TrapEvent(BaseModel):
    """One trap firing, and where in the match it happened."""

    event_id: UUID
    timestamp: datetime
    #: The trap tool that fired (``watch_file``, ``watch_process``, ``auto_kill``).
    trap: str | None
    #: What the trap was watching: the path or the process name. This is what
    #: tells two firings of the same trap tool apart.
    target: str | None = None
    #: The Prisoner's turn that was in progress when it fired. A trap fires from
    #: a sandbox observation rather than from a tool call, so this is the turn
    #: it happened during, not the action that caused it.
    prisoner_turn: int | None = None
    #: The Warden's turn at the same moment.
    warden_turn: int | None = None


class MatchEventRecord(BaseModel):
    """A raw match event, for anything the shaped listings do not cover."""

    event_id: UUID
    timestamp: datetime
    actor: str
    event_type: str
    action: dict[str, Any]
    result: dict[str, Any] | None


class ConversationEntry(BaseModel):
    """One message of an agent's stored conversation, flattened for reading.

    The stored form is pydantic-ai's own message dump. This is the same content
    resolved into one row per step, so a reviewer can page through it without
    parsing the wire format.
    """

    #: Position in the conversation, so a page can be resumed by index.
    index: int
    kind: str
    #: ``prisoner`` / ``warden`` for a prompt, else ``None``.
    actor: str | None = None
    #: Text the agent read or wrote, when the step carries any.
    text: str | None = None
    #: Tool name for a call or a return.
    tool_name: str | None = None
    tool_call_id: str | None = None
    #: Arguments of a tool call, or the payload of a tool return.
    content: dict[str, Any] | None = None
