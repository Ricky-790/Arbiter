"""Shell-backed agent tools."""

from app.agents.models import AgentType

from .base import BaseTool
from .execution import ToolExecutionContext
from .models import ToolCost, ToolResult

#: Most characters one Prisoner ``bash`` call may return, stdout and stderr
#: counted separately. The Engine enforces it; it lives here because the tool
#: description below is where the model learns about it.
#:
#: The Prisoner is the side that gains from bulk reconnaissance, and nothing
#: else bounds a single command: chaining five or six ``cat``s into one charged
#: action otherwise returns a whole filesystem in one go. Four thousand
#: characters comfortably fits ``ls -la``, ``ps aux`` and a page of ``grep``
#: hits while cutting a file dump by an order of magnitude.
#:
#: The Warden is deliberately uncapped. Its shell output is its own diagnostics
#: for the defence it is running, and this is a Prisoner-side balance rule, not
#: a shared transfer limit.
PRISONER_BASH_OUTPUT_CHARS = 4000


class BashTool(BaseTool):
    """Execute an arbitrary command in the actor's sandbox environment."""

    def __init__(self) -> None:
        super().__init__(
            name="bash",
            description=(
                "Execute an arbitrary shell command in your sandbox. example: ls -la / | grep 'home'. "
                "Commands run with your own account's permissions; the other agent's home "
                "directory is off limits. "
                f"The Prisoner's output is capped at {PRISONER_BASH_OUTPUT_CHARS} characters "
                "per call -- longer output is truncated and you are told by how much, so "
                "prefer grep/head/wc and narrow commands."
            ),
            allowed_agents=frozenset({AgentType.PRISONER, AgentType.WARDEN}),
            cost=ToolCost.BASH,
        )

    async def execute(
        self, context: ToolExecutionContext, *, command: str
    ) -> ToolResult:
        return await context.run_command(command=command)
