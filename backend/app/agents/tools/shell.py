"""Shell-backed agent tools."""

from app.agents.models import AgentType

from .base import BaseTool
from .execution import ToolExecutionContext
from .models import ToolCost, ToolResult


class BashTool(BaseTool):
    """Execute an arbitrary command in the actor's sandbox environment."""

    def __init__(self) -> None:
        super().__init__(
            name="bash",
            description="Execute an arbitrary shell command in your sandbox. example: ls -la / | grep 'home'",
            allowed_agents=frozenset({AgentType.PRISONER, AgentType.WARDEN}),
            cost=ToolCost.BASH,
        )

    async def execute(
        self, context: ToolExecutionContext, *, command: str
    ) -> ToolResult:
        return await context.run_command(command=command)
