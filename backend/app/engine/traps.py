"""State-only Warden trap management; monitoring stays in the sandbox layer."""

from app.agents.tools.models import ToolCall
from app.sandbox.models import SandboxEvent, SandboxEventType

from .models import ActiveTrap, MatchState

TRAP_TOOL_NAMES = frozenset({"watch_file", "watch_process", "auto_kill"})


class TrapManager:
    def validate_arm(self, state: MatchState, call: ToolCall) -> str | None:
        if call.name not in TRAP_TOOL_NAMES:
            return None
        if state.active_trap is not None:
            return "Only one trap may be active at a time"
        if state.blocked_trap_name == call.name:
            return f"{call.name} cannot be re-armed as the next Warden action after it triggers"
        return None

    def arm(self, state: MatchState, call: ToolCall) -> None:
        if call.name == "watch_file":
            target = str(call.arguments["path"])
        else:
            target = str(call.arguments["process"])
        state.active_trap = ActiveTrap(tool_name=call.name, target=target)
        state.blocked_trap_name = None

    def matches(self, state: MatchState, event: SandboxEvent) -> bool:
        trap = state.active_trap
        if trap is None:
            return False
        if trap.tool_name == "watch_file":
            return event.path is not None and event.path == trap.target
        return (
            event.type is SandboxEventType.PROCESS_STARTED
            and event.process_name is not None
            and event.process_name == trap.target
        )

    def trigger(self, state: MatchState) -> ActiveTrap | None:
        trap = state.active_trap
        if trap is None:
            return None
        state.active_trap = None
        state.blocked_trap_name = trap.tool_name
        return trap
