"""Base class and result shaping for the reviewer agent's tools.

These are not match actions. They borrow ``ToolRegistry`` and the
``ToolChoosingAgent`` tool-definition machinery -- which build a model-facing
schema from a typed ``execute()`` signature -- but they have no ``AgentType``
they belong to and no credit cost, so they get their own base rather than
pretending to be a ``BaseTool``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from app.agents.tokens import count_tokens, lower_token_limit
from app.agents.tools.models import ToolResult

from .context import ReviewContext


class ReviewTool(ABC):
    """One read-only question the reviewer agent can ask.

    ``execute`` takes a :class:`ReviewContext` instead of a
    ``ToolExecutionContext``: there is no sandbox here, only a match to read.
    The context carries the match id so it never appears in the tool's
    arguments -- the schema the model sees lists only what it may choose.

    Return JSON in ``output``: the model reads structure, and a page's
    ``total``/``has_more`` is how it knows whether to ask for more.
    """

    name: str
    description: str

    @abstractmethod
    async def execute(self, context: ReviewContext, **kwargs: Any) -> ToolResult:
        """Answer one question about the bound match."""

    def is_available_to(self, agent_type: Any) -> bool:
        """Always false: these are never offered inside a match.

        Present so a review registry is still a well-formed ``ToolRegistry``
        member -- ``get_for_agent`` returns nothing for a Prisoner or Warden
        rather than raising.
        """
        return False


def json_result(model: Any) -> ToolResult:
    """Serialize one reviewer model as a tool result, with a size warning.

    Sent in full, never truncated: a silently shortened match is worse than a
    large one, because the agent would reason from missing data without knowing
    it. When the payload is over budget the agent is told which knob to turn
    instead.
    """
    payload = json.dumps(
        model.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    tokens = count_tokens(payload)
    limit = lower_token_limit()
    notice = None
    if tokens > limit:
        notice = (
            f"This page is ~{tokens} tokens, over the ~{limit} budget. Ask for "
            "fewer items (a smaller n), narrow it to one side with user, or "
            "page on with offset to read the rest in smaller pieces."
        )
    return ToolResult(success=True, output=payload, notice=notice)


def failed(error: str) -> ToolResult:
    """A recoverable refusal the agent can read and correct."""
    return ToolResult(success=False, error=error)
