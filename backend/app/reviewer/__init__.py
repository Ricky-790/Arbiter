"""Read-only match review: the data a human or an agent needs to critique a match.

Nothing in this package writes. See ``service`` for the individual, paginated
queries, and ``AGENTS.md`` for the constraints they must keep.
"""

from . import service
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

__all__ = [
    "AgentBriefing",
    "ConversationEntry",
    "MatchEventRecord",
    "MatchOverview",
    "MatchStats",
    "Page",
    "SideStats",
    "ThoughtRecord",
    "ToolCallRecord",
    "TrapEvent",
    "service",
]
