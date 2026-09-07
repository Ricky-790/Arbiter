from app.agents.models import AgentType

from .base import BaseTool
from .execution import ToolExecutionContext
from .models import ToolCost, ToolResult


class WatchFileTool(BaseTool):
    """Ask the execution layer to monitor activity affecting a path."""

    def __init__(self) -> None:
        super().__init__(
            name="watch_file",
            description="Monitor activity affecting a file or directory path.",
            allowed_agents=frozenset({AgentType.WARDEN}),
            cost=ToolCost.WATCH_FILE,
        )

    async def execute(self, context: ToolExecutionContext, *, path: str) -> ToolResult:
        return await context.watch_file(path=path)
