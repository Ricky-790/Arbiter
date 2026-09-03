from pydantic_ai import Agent

from app.agents.agents_directory import agents_mapper
from app.agents.instructions import SETUP_AGENT_INSTRUCTIONS, SETUP_AGENT_PROMPT
from app.agents.models import ChallengeConfig, ChallengeSetup
from app.logger import get_logger

logger = get_logger()


class SetupAgent:
    """Agent that generates challenge setup scripts."""

    def __init__(self, model_name: str = "gemini-3.1-flash-lite"):
        model = agents_mapper.get(model_name)
        if model is None:
            raise ValueError(f"Unknown model: {model_name}")

        self.agent = Agent(
            model,
            instructions=SETUP_AGENT_INSTRUCTIONS,
            output_type=ChallengeSetup,
        )
        logger.info("Initialized SetupAgent with model: %s", model_name)

    async def generate_setup(self, challenge: ChallengeConfig) -> ChallengeSetup:
        """Generate a challenge setup from a ChallengeConfig.

        Args:
            challenge: ChallengeConfig with win_condition, difficulty, theme

        Returns:
            ChallengeSetup with script, flag, and reasoning
        """
        prompt = self._build_prompt(challenge)
        result = await self.agent.run(prompt)
        return result.output

    def _build_prompt(self, challenge: ChallengeConfig) -> str:
        """Build prompt from ChallengeConfig."""
        return SETUP_AGENT_PROMPT.format(
            win_condition=challenge.win_condition,
            difficulty=challenge.difficulty,
            theme=challenge.theme if challenge.theme else "Your choice",
        )
