from collections.abc import Iterable

from app.agents.models import AgentType

from .base import BaseTool


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] = ()) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"A tool named {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"Unknown tool: {name!r}") from error

    def get_for_agent(self, agent_type: AgentType) -> list[BaseTool]:
        return [
            tool for tool in self._tools.values() if tool.is_available_to(agent_type)
        ]

    def get_descriptions_for_agent(self, agent_type: AgentType) -> list[str]:
        return [
            tool.tool_description()
            for tool in self._tools.values()
            if tool.is_available_to(agent_type)
        ]


def build_default_registry() -> ToolRegistry:
    """Create the initial Arbiter capability set without duplicate instances."""
    from .filesystem import WatchFileTool
    from .network import BlockNetworkTool
    from .process import AutoKillTool, KillProcessTool, WatchProcessTool
    from .shell import BashTool
    from .system import PassTool, SubmitFlagTool

    return ToolRegistry(
        [
            BashTool(),
            WatchFileTool(),
            WatchProcessTool(),
            KillProcessTool(),
            AutoKillTool(),
            BlockNetworkTool(),
            SubmitFlagTool(),
            PassTool(),
        ]
    )
