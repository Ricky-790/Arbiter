"""Game-level actions that do not execute ordinary shell commands."""

from typing import Any

from app.agents.models import AgentType

from .base import BaseTool
from .execution import ToolExecutionContext
from .models import ToolCost, ToolResult


class SubmitFlagTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="submit_flag",
            description=(
                "Submit your answer for engine-side verification. Provide a "
                "JSON object whose fields match the challenge's flag "
                "structure, e.g. {\"value\": \"secret123\"}."
            ),
            allowed_agents=frozenset({AgentType.PRISONER}),
            cost=ToolCost.SUBMIT_FLAG,
        )

    async def execute(
        self,
        context: ToolExecutionContext,
        *,
        response: dict[str, Any],
    ) -> ToolResult:
        return await context.submit_flag(response=response)


class PassTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="pass",
            description="Take no action at this opportunity.",
            allowed_agents=frozenset({AgentType.PRISONER, AgentType.WARDEN}),
            cost=ToolCost.PASS,
        )

    async def execute(self, context: ToolExecutionContext) -> ToolResult:
        return await context.pass_turn()
