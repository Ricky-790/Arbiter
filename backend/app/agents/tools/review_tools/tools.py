"""The reviewer agent's read-only tools, one per question it can ask.

Each is a thin wrapper over ``app.reviewer``: the reviewer owns what is
readable and how it is shaped, and these only choose which question to put to
it. None takes a match id -- it comes from the bound :class:`ReviewContext`.

Every page is returned whole, with its ``total`` and ``has_more``, so the agent
decides what to pull next instead of being handed the match up front.
"""

from __future__ import annotations

from app.agents.tools.models import ToolResult
from app.db.models import EVENT_TYPES
from app.reviewer import service as reviewer
from app.reviewer.service import REVIEWABLE_ACTORS

from .base import ReviewTool, failed, json_result
from .context import ReviewContext

#: Shared wording, so every tool that lists calls describes them the same way.
_CALL_SHAPE = (
    "Each entry has the tool, its arguments, whether it succeeded, its exit "
    "code, and why it failed or was refused if it was."
)
_PAGE_SHAPE = (
    "Returns JSON with items, total, offset, limit and has_more: raise offset "
    "by limit to read on, or lower n for smaller pages."
)


def _actor_error(user: str | None) -> str | None:
    """Reject a side that does not exist, before the reviewer has to."""
    if user is None or user in REVIEWABLE_ACTORS:
        return None
    return f"user must be one of {', '.join(REVIEWABLE_ACTORS)}; got {user!r}"


def _bounds_error(n: int, offset: int) -> str | None:
    if n < 1:
        return f"n must be at least 1; got {n}"
    if offset < 0:
        return f"offset must not be negative; got {offset}"
    return None


class GetMatchSummaryTool(ReviewTool):
    name = "get_match_summary"
    description = (
        "What the match was: challenge name and description, win condition, "
        "both sides' provider and model, when it ran, how long it took, who won "
        "and why, and the strategy each side was started with. Takes no "
        "arguments. Start here."
    )

    async def execute(self, context: ReviewContext) -> ToolResult:
        overview = await reviewer.get_match_overview(context.match_id)
        if overview is None:
            return failed("No match has that id.")
        return json_result(overview)


class GetMatchStatsTool(ReviewTool):
    name = "get_match_stats"
    description = (
        "Both sides' totals: credits left, how many actions each requested, "
        "how many succeeded, failed or were refused, which tools each used and "
        "how often, each side's own trap counters, and which trap tools fired. "
        "Takes no arguments. Cheap; use it to decide where to look closer."
    )

    async def execute(self, context: ReviewContext) -> ToolResult:
        stats = await reviewer.get_match_stats(context.match_id)
        if stats is None:
            return failed("No match has that id.")
        return json_result(stats)


class GetAgentBriefingTool(ReviewTool):
    name = "get_agent_briefing"
    description = (
        "The opening message one side was given, including its challenge hint "
        "and the strategy it was told to try. Takes user=prisoner or "
        "user=warden."
    )

    async def execute(self, context: ReviewContext, *, user: str) -> ToolResult:
        if (error := _actor_error(user)) is not None:
            return failed(error)
        briefing = await reviewer.get_agent_briefing(context.match_id, user)
        if briefing is None:
            return failed(
                f"No opening message is stored for the {user} in this match."
            )
        return json_result(briefing)


class GetToolCallsTool(ReviewTool):
    name = "get_tool_calls"
    description = (
        "A page of the actions the agents requested, oldest first. "
        f"{_CALL_SHAPE} Optional: user=prisoner|warden to take one side, "
        "success_only=true to skip refused and failed calls, n (default 20) for "
        "how many, offset to page on. This is the best record of what was "
        f"actually attempted. {_PAGE_SHAPE}"
    )

    async def execute(
        self,
        context: ReviewContext,
        *,
        n: int = 20,
        user: str | None = None,
        offset: int = 0,
        success_only: bool = False,
    ) -> ToolResult:
        if (error := _actor_error(user)) is not None:
            return failed(error)
        if (error := _bounds_error(n, offset)) is not None:
            return failed(error)
        page = await reviewer.get_tool_calls(
            context.match_id,
            user,
            offset=offset,
            limit=n,
            success_only=success_only,
        )
        return json_result(page)


class GetMessagesTool(ReviewTool):
    name = "get_messages"
    description = (
        "A page of one side's full conversation, oldest first: what it was "
        "told, what it said, every tool call it made and every result it got "
        "back. Takes user=prisoner or user=warden (required), n (default 20) "
        "for how many entries, and offset to page on. This is the most detailed "
        f"view and the largest, so page it rather than pulling it all. "
        f"{_PAGE_SHAPE}"
    )

    async def execute(
        self,
        context: ReviewContext,
        *,
        user: str,
        n: int = 20,
        offset: int = 0,
    ) -> ToolResult:
        if (error := _actor_error(user)) is not None:
            return failed(error)
        if (error := _bounds_error(n, offset)) is not None:
            return failed(error)
        page = await reviewer.get_conversation(
            context.match_id, user, offset=offset, limit=n
        )
        return json_result(page)


class GetThoughtsTool(ReviewTool):
    name = "get_thoughts"
    description = (
        "A page of what the agents deliberately reported for the match log, "
        "oldest first. This is their own commentary, not private reasoning -- "
        "Arbiter never records a model's hidden thinking, so there is none to "
        "ask for. Optional user=prisoner|warden, n (default 20), offset. "
        f"{_PAGE_SHAPE}"
    )

    async def execute(
        self,
        context: ReviewContext,
        *,
        user: str | None = None,
        n: int = 20,
        offset: int = 0,
    ) -> ToolResult:
        if (error := _actor_error(user)) is not None:
            return failed(error)
        if (error := _bounds_error(n, offset)) is not None:
            return failed(error)
        page = await reviewer.get_agent_thoughts(
            context.match_id, user, offset=offset, limit=n
        )
        return json_result(page)


class GetTrapEventsTool(ReviewTool):
    name = "get_trap_events"
    description = (
        "A page of trap firings, oldest first: which trap went off, what it was "
        "watching, and the turn each side was on when it fired. Optional n "
        f"(default 20) and offset. {_PAGE_SHAPE}"
    )

    async def execute(
        self,
        context: ReviewContext,
        *,
        n: int = 20,
        offset: int = 0,
    ) -> ToolResult:
        if (error := _bounds_error(n, offset)) is not None:
            return failed(error)
        page = await reviewer.get_trap_events(
            context.match_id, offset=offset, limit=n
        )
        return json_result(page)


class GetMatchEventsTool(ReviewTool):
    name = "get_match_events"
    description = (
        "A page of the raw match events, oldest first. The catch-all for what "
        "the shaped views do not cover: the match starting and finishing, "
        "sandbox observations, provider errors and retries. Optional "
        "event_type to filter by one exact type, user=prisoner|warden, n "
        f"(default 20) and offset. {_PAGE_SHAPE}"
    )

    async def execute(
        self,
        context: ReviewContext,
        *,
        n: int = 20,
        offset: int = 0,
        event_type: str | None = None,
        user: str | None = None,
    ) -> ToolResult:
        if event_type is not None and event_type not in EVENT_TYPES:
            return failed(
                f"Unknown event_type {event_type!r}; known types are "
                f"{', '.join(EVENT_TYPES)}."
            )
        if (error := _actor_error(user)) is not None:
            return failed(error)
        if (error := _bounds_error(n, offset)) is not None:
            return failed(error)
        page = await reviewer.get_match_events(
            context.match_id,
            event_type=event_type,
            actor=user,
            offset=offset,
            limit=n,
        )
        return json_result(page)
