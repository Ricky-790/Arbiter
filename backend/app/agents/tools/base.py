import inspect
from abc import ABC, abstractmethod

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

    def tool_description(self) -> str:
        signature = inspect.signature(self.execute)

        arguments = []

        for name, parameter in signature.parameters.items():
            if name in {"self", "context"}:
                continue

            annotation = parameter.annotation

            if annotation is inspect.Parameter.empty:
                type_name = "Any"
            elif isinstance(annotation, type):
                type_name = annotation.__name__
            else:
                type_name = str(annotation)

            default = ""
            if parameter.default is not inspect.Parameter.empty:
                default = f", default={parameter.default!r}"

            arguments.append(f"- {name} ({type_name}{default})")

        args_text = "\n".join(arguments) if arguments else "- None"

        return f"""Tool: {self.name}

    Description:
    {self.description}

    Arguments:
    {args_text}

    Cost: {self.cost.value}
    """

    def is_available_to(self, agent_type: AgentType) -> bool:
        return agent_type in self.allowed_agents

    @abstractmethod
    async def execute(
        self, context: ToolExecutionContext, *args, **kwargs
    ) -> ToolResult:
        """Delegate an already-authorized action to the supplied context."""
        my_args = kwargs
        pass
