from app.agents.models import AgentType

from .base import BaseTool
from .execution import ToolExecutionContext
from .models import ToolCost, ToolResult


class BlockNetworkTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="block_network",
            description="Block all network traffic or traffic to an optional IP and port.",
            allowed_agents=frozenset({AgentType.WARDEN}),
            cost=ToolCost.BLOCK_NETWORK,
        )

    async def execute(
        self,
        context: ToolExecutionContext,
        *,
        ip: str | None = None,
        port: int | None = None,
    ) -> ToolResult:
        return await context.block_network(ip=ip, port=port)
