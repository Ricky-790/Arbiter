from app.agents.models import AgentType

from .base import BaseTool
from .execution import ToolExecutionContext
from .models import ToolCost, ToolResult


class WatchProcessTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="watch_process",
            description="Monitor processes matching a process name or pattern.",
            allowed_agents=frozenset({AgentType.WARDEN}),
            cost=ToolCost.WATCH_PROCESS,
        )

    async def execute(
        self, context: ToolExecutionContext, *, process: str
    ) -> ToolResult:
        return await context.watch_process(process=process)


class KillProcessTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="kill_process",
            description="Terminate the process with the supplied PID.",
            allowed_agents=frozenset({AgentType.WARDEN}),
            cost=ToolCost.KILL_PROCESS,
        )

    async def execute(self, context: ToolExecutionContext, *, pid: int) -> ToolResult:
        return await context.kill_process(pid=pid)


class AutoKillTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="auto_kill",
            description="Register a rule to automatically terminate matching processes.",
            allowed_agents=frozenset({AgentType.WARDEN}),
            cost=ToolCost.AUTO_KILL,
        )

    async def execute(
        self, context: ToolExecutionContext, *, process: str
    ) -> ToolResult:
        return await context.auto_kill(process=process)
