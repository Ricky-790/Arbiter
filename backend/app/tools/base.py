from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.sandbox.manager import SandboxManager
from app.tools.models import ToolCost, ToolResult


class BaseTool(ABC):
    """Base class for all tools."""

    name: str
    description: str
    cost: int
    agent_type: str  # "prisoner", "warden", or "both"
    params_schema: dict[str, Any]

    def __init__(self):
        self.cost = self._get_cost()

    def _get_cost(self) -> int:
        """Get cost from ToolCost enum based on tool name."""
        try:
            return ToolCost[self.name.upper()].value
        except KeyError:
            return 1

    @abstractmethod
    async def execute(
        self, sandbox_manager: SandboxManager, match_id: str, params: dict[str, Any]
    ) -> ToolResult:
        """Execute the tool.

        Args:
            sandbox_manager: The SandboxManager instance
            match_id: The match ID to execute in
            params: Tool-specific parameters

        Returns:
            ToolResult with success, output, error, and cost
        """
        pass

    def validate_params(self, params: dict[str, Any]) -> Optional[str]:
        """Validate parameters. Returns error message or None."""
        return None

    def to_llm_schema(self) -> dict[str, Any]:
        """Convert to schema for LLM function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.params_schema,
        }


class ToolRegistry:
    """Registry of all available tools."""

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool):
        cls._tools[tool.name] = tool

    @classmethod
    def get(cls, name: str) -> Optional[BaseTool]:
        return cls._tools.get(name)

    @classmethod
    def get_for_agent(cls, agent_type: str) -> dict[str, BaseTool]:
        """Get tools available to a specific agent type."""
        return {
            name: tool
            for name, tool in cls._tools.items()
            if tool.agent_type in (agent_type, "both")
        }

    @classmethod
    def list_all(cls) -> Dict[str, BaseTool]:
        return cls._tools.copy()

    @classmethod
    def to_llm_tools(cls, agent_type: str) -> list:
        """Get tools formatted for LLM API (Anthropic/OpenAI)."""
        tools = cls.get_for_agent(agent_type)
        return [tool.to_llm_schema() for tool in tools.values()]
