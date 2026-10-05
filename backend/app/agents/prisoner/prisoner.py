from collections.abc import Iterable

from app.agents.base import ToolChoosingAgent, with_tips
from app.agents.tools.models import ToolCall

from .instructions import PRISONER_INSTRUCTIONS


class PrisonerAgent(ToolChoosingAgent):
    def __init__(
        self,
        model_name: str = "openai:gpt-4o-mini",
        *,
        objective: str | None = None,
        scripted_calls: Iterable[ToolCall] | None = None,
        api_key: str | None = None,
    ) -> None:
        """``instructions`` are optional operator tips appended to the role
        instructions (see :func:`app.agents.base.with_tips`). ``api_key`` is
        required: every model in the directory is BYOK."""
        super().__init__(
            model_name=model_name,
            instructions=PRISONER_INSTRUCTIONS,
            allowed_tools={
                "bash",
                "read_file",
                "write_file",
                "write_to_scratchpad",
                "submit_flag",
                "pass",
            },
            objective=objective,
            scripted_calls=scripted_calls,
            api_key=api_key,
        )
