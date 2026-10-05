"""The reviewer agent's read-only toolset.

Kept apart from ``build_default_registry()``: those tools are match actions the
Engine authorizes, these are questions asked about a finished match, and the
reviewer agent must never be handed a way to act inside a match.
"""

from __future__ import annotations

from app.agents.tools.registry import ToolRegistry

from .base import ReviewTool, failed, json_result
from .context import ReviewContext
from .tools import (
    GetAgentBriefingTool,
    GetMatchEventsTool,
    GetMatchStatsTool,
    GetMatchSummaryTool,
    GetMessagesTool,
    GetThoughtsTool,
    GetToolCallsTool,
    GetTrapEventsTool,
)

#: Tool names the reviewer agent is allowed, in the order they are defined.
REVIEW_TOOL_NAMES: frozenset[str] = frozenset(
    {
        GetMatchSummaryTool.name,
        GetMatchStatsTool.name,
        GetAgentBriefingTool.name,
        GetToolCallsTool.name,
        GetMessagesTool.name,
        GetThoughtsTool.name,
        GetTrapEventsTool.name,
        GetMatchEventsTool.name,
    }
)


def build_review_registry() -> ToolRegistry:
    """Every read-only review capability, ready to expose to the agent."""
    return ToolRegistry(
        [
            GetMatchSummaryTool(),
            GetMatchStatsTool(),
            GetAgentBriefingTool(),
            GetToolCallsTool(),
            GetMessagesTool(),
            GetThoughtsTool(),
            GetTrapEventsTool(),
            GetMatchEventsTool(),
        ]
    )


__all__ = [
    "REVIEW_TOOL_NAMES",
    "ReviewContext",
    "ReviewTool",
    "build_review_registry",
    "failed",
    "json_result",
]
