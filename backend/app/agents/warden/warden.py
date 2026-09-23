from collections.abc import Iterable

from app.agents.base import ToolChoosingAgent, with_tips
from app.agents.tools.models import ToolCall

from .instructions import WARDEN_INSTRUCTIONS


class WardenAgent(ToolChoosingAgent):
    def __init__(
        self,
        model_name: str = "google/gemini-3.1-flash-lite",
        *,
        objective: str | None = None,
        instructions: str | None = None,
        scripted_calls: Iterable[ToolCall] | None = None,
        api_key: str | None = None,
    ) -> None:
        """``instructions`` are optional operator tips appended to the role
        instructions (see :func:`app.agents.base.with_tips`). ``api_key`` is
        required only when ``model_name`` names a BYOK model."""
        super().__init__(
            model_name=model_name,
            instructions=with_tips(WARDEN_INSTRUCTIONS, instructions),
            allowed_tools={
                "bash",
                "read_file",
                "write_file",
                "write_to_scratchpad",
                "watch_file",
                "watch_process",
                "kill_process",
                "auto_kill",
                "block_network",
                "peek_prisoner_logs",
                "pass",
            },
            objective=objective,
            scripted_calls=scripted_calls,
            api_key=api_key,
        )
