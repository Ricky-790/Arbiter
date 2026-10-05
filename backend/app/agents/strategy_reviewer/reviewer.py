"""The Strategy Reviewer agent: reads one match, proposes a better strategy.

Unlike the Prisoner and Warden it plays nothing. It has no Engine, no sandbox
and no opponent, so it binds its own executor and runs its own read-only tools
against the match fixed in its :class:`ReviewContext`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_ai import ToolReturn
from pydantic_ai.exceptions import ModelHTTPError

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

    #: Bound the model requests, this is unsupervised step
    _request_limit: int | None = 30

    #: Cooldown before retrying a retryable provider failure (429/503/504).
    #:
    #: A review is one-shot with nobody pacing it: the caller is watching a
    #: stream, not a match clock, so a provider hiccup is worth riding out
    #: instead of failing the whole review. Longer than a match agent's 30s
    #: because a review has no wall clock to respect -- the match's timing is
    #: deliberately *not* this path.
    _review_retry_wait_seconds: float = 45.0

    @classmethod
    def _retry_wait(cls, error: ModelHTTPError, *, status: int) -> float:
        """A flat 45s cooldown for every retryable provider failure.

        The base class honours the provider's ``Retry-After`` and otherwise
        waits 30s. The reviewer fixes one number instead. Waiting longer than a
        provider asks is always safe -- it can only help the limit clear -- and
        a predictable delay is easier to reason about than one that varies per
        response, especially since a short ``Retry-After`` would just retry
        back into the same limit and spend one of the three attempts.
        """
        return cls._review_retry_wait_seconds

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
