"""The Strategy Reviewer agent: reads one match, proposes a better strategy.

Unlike the Prisoner and Warden it plays nothing. It has no Engine, no sandbox
and no opponent, so it binds its own executor and runs its own read-only tools
against the match fixed in its :class:`ReviewContext`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import ToolReturn

from app.agents.base import ToolChoosingAgent
from app.agents.tools.models import ToolCall, ToolResult
from app.agents.tools.review_tools import (
    REVIEW_TOOL_NAMES,
    ReviewContext,
    build_review_registry,
)
from app.logger import get_logger

from .instructions import STRATEGY_REVIEWER_INSTRUCTIONS
from .prompt import ReviewRequest, build_review_prompt

logger = get_logger()

#: Progress callback: (event_type, attributes). Used to stream what the review
#: is doing, never what the model is privately thinking.
ReviewEventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


class StrategyReviewerAgent(ToolChoosingAgent):
    """One review run: read a finished match, write the next strategy.

    The match id lives in the bound context, never in a tool argument, so the
    model cannot widen its own scope -- it chooses *which question* to ask, not
    which match to ask about.
    """

    #: A review is one run with nobody pacing it, so bound the model requests.
    #: Generous for the eight tools available, low enough that a reviewer that
    #: keeps asking without concluding ends in a failure rather than a bill.
    _request_limit: int | None = 30

    def __init__(
        self,
        *,
        model_name: str,
        request: ReviewRequest,
        context: ReviewContext,
        api_key: str | None = None,
        on_event: ReviewEventSink | None = None,
    ) -> None:
        super().__init__(
            model_name=model_name,
            instructions=STRATEGY_REVIEWER_INSTRUCTIONS,
            allowed_tools=set(REVIEW_TOOL_NAMES),
            registry=build_review_registry(),
            objective=None,
            api_key=api_key,
        )
        self._context = context
        self._review_prompt = build_review_prompt(request)
        # Reports both the agent's own provider events (retries, errors) and
        # the tool activity below, so one sink drives the whole progress stream.
        if on_event is not None:
            self.bind_event_reporter(on_event)
        self.bind_tool_executor(self._run_review_tool)

    def _turn_prompt(self, scratchpad: str) -> str:
        """The review request, not a match objective.

        There is no scratchpad and no match to play: the challenge framing and
        the strategy under review are the whole task.
        """
        return self._review_prompt

    async def _run_review_tool(self, call: ToolCall) -> Any:
        """Run one review tool against the bound match and report progress.

        Stands in for the Engine's executor. There is nothing to authorize
        here: every review tool is a read of the same match, and the match id
        is not the model's to choose.
        """
        await self._report_event(
            "review_tool_call", tool=call.name, arguments=call.arguments
        )
        try:
            tool = self._registry.get(call.name)
            result = await tool.execute(self._context, **call.arguments)
        except Exception as error:
            logger.exception(f"Review tool {call.name} failed")
            result = ToolResult(success=False, error=f"Tool call failed: {error}")
        await self._report_event(
            "review_tool_result",
            tool=call.name,
            success=result.success,
            error=result.error,
        )
        return ToolReturn(
            return_value=result.model_dump(exclude_none=True, exclude={"metadata"})
        )
