from collections.abc import Iterable

from app.agents.base import ToolChoosingAgent
from app.agents.tools.models import ToolCall

from .instructions import PRISONER_INSTRUCTIONS


class PrisonerAgent(ToolChoosingAgent):
    def __init__(
        self,
        model_name: str = "gemini-3.1-flash-lite",
        *,
        objective: str | None = None,
        scripted_calls: Iterable[ToolCall] | None = None,
    ) -> None:
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
        )
