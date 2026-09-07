from datetime import datetime, timedelta

from app.agents.models import AgentType

from .models import MatchState, utc_now


class CooldownManager:
    def __init__(self, duration: timedelta = timedelta(seconds=5)) -> None:
        self.duration = duration

    def can_act(
        self, state: MatchState, actor: AgentType, now: datetime | None = None
    ) -> bool:
        now = now or utc_now()
        agent_state = self._agent_state(state, actor)
        if actor is AgentType.WARDEN and agent_state.reaction_until:
            if now < agent_state.reaction_until:
                return True
            agent_state.reaction_until = None
        return agent_state.cooldown_until is None or now >= agent_state.cooldown_until

    def start(
        self, state: MatchState, actor: AgentType, now: datetime | None = None
    ) -> None:
        now = now or utc_now()
        agent_state = self._agent_state(state, actor)
        agent_state.cooldown_until = now + self.duration
        if actor is AgentType.WARDEN:
            agent_state.reaction_until = None

    def open_warden_reaction(
        self, state: MatchState, now: datetime | None = None
    ) -> datetime:
        now = now or utc_now()
        state.warden.cooldown_until = now
        state.warden.reaction_until = now + self.duration
        return state.warden.reaction_until

    @staticmethod
    def _agent_state(state: MatchState, actor: AgentType):
        return state.prisoner if actor is AgentType.PRISONER else state.warden
