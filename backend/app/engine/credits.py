"""Credit accounting for one match."""

from app.agents.models import AgentType
from app.agents.tools.models import ToolCost

from .models import MatchState


class CreditManager:
    def can_afford(self, state: MatchState, actor: AgentType, cost: ToolCost) -> bool:
        return self._agent_state(state, actor).credits >= int(cost)

    def deduct(self, state: MatchState, actor: AgentType, cost: ToolCost) -> int:
        agent_state = self._agent_state(state, actor)
        if agent_state.credits < int(cost):
            raise ValueError("Insufficient credits")
        agent_state.credits -= int(cost)
        return agent_state.credits

    @staticmethod
    def _agent_state(state: MatchState, actor: AgentType):
        return state.prisoner if actor is AgentType.PRISONER else state.warden
