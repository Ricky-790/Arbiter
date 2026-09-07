from abc import ABC, abstractmethod
from typing import Any

from app.agents.models import AgentType

from .execution import ToolExecutionContext
from .models import ToolCost, ToolResult


class BaseTool(ABC):
    """A small declarative capability; game rules are enforced by the Engine."""

    name: str
    description: str
    allowed_agents: frozenset[AgentType]
    cost: ToolCost

    def __init__(
        self,
        *,
        name: str,
        description: str,
        allowed_agents: frozenset[AgentType],
        cost: ToolCost,
    ) -> None:
        self.name = name
        self.description = description
        self.allowed_agents = allowed_agents
        self.cost = cost

    def is_available_to(self, agent_type: AgentType) -> bool:
        return agent_type in self.allowed_agents

    @abstractmethod
    async def execute(
        self, context: ToolExecutionContext, *args, **kwargs
    ) -> ToolResult:
        """Delegate an already-authorized action to the supplied context."""
        my_args = kwargs
        pass
