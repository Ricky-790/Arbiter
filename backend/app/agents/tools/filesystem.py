from app.agents.models import AgentType

from .base import BaseTool
from .execution import ToolExecutionContext
from .models import ToolCost, ToolResult


class ReadFileTool(BaseTool):
    """Read a file inside the actor's sandbox environment."""

    def __init__(self) -> None:
        super().__init__(
            name="read_file",
            description=(
                "Read the contents of a file. Runs with your own user permissions; files you cannot read will fail."
            ),
            allowed_agents=frozenset({AgentType.PRISONER, AgentType.WARDEN}),
            cost=ToolCost.READ_FILE,
        )

    async def execute(self, context: ToolExecutionContext, *, path: str) -> ToolResult:
        return await context.read_file(path=path)


class WriteFileTool(BaseTool):
    """Write content to a file inside the actor's sandbox environment."""

    def __init__(self) -> None:
        super().__init__(
            name="write_file",
            description=(
                "Write content to a file at the given absolute path(including extension). Parent directories are created as needed. File paths will be prepended with a fixed dir route, to allow only writing to specific locations."
            ),
            allowed_agents=frozenset({AgentType.PRISONER, AgentType.WARDEN}),
            cost=ToolCost.WRITE_FILE,
        )

    async def execute(
        self, context: ToolExecutionContext, *, path: str, content: str
    ) -> ToolResult:
        return await context.write_file(path=path, content=content)


class WriteToScratchpadTool(BaseTool):
    """Append content to the actor's private sandbox scratchpad."""

    def __init__(self) -> None:
        super().__init__(
            name="write_to_scratchpad",
            description=(
                "Append content to your scratchpad. Note your key observations to carry on to the next iteration sandbox. No path is needed."
            ),
            allowed_agents=frozenset({AgentType.PRISONER, AgentType.WARDEN}),
            cost=ToolCost.WRITE_SCRATCHPAD,
        )

    async def execute(
        self, context: ToolExecutionContext, *, content: str
    ) -> ToolResult:
        return await context.write_to_scratchpad(content=content)


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
