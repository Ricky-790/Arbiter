"""State-only Warden trap management; monitoring stays in the sandbox layer."""

from app.agents.tools.models import ToolCall
from app.sandbox.models import SandboxEvent, SandboxEventType

from .models import ActiveTrap, MatchState

TRAP_TOOL_NAMES = frozenset({"watch_file", "watch_process", "auto_kill"})

#: Most traps the Warden may have armed and unresolved at one time.
#:
#: Two is enough to cover a likely path and a backup without letting the
#: Warden blanket the sandbox: traps are cheap to arm and each one is a firing
#: the Prisoner never sees coming, so an unbounded number would make the
#: reaction window the whole game. A slot frees up when its trap fires.
MAX_ACTIVE_TRAPS = 2


class TrapManager:
    def validate_arm(self, state: MatchState, call: ToolCall) -> str | None:
        if call.name not in TRAP_TOOL_NAMES:
            return None
        if len(state.active_traps) >= MAX_ACTIVE_TRAPS:
            return (
                f"At most {MAX_ACTIVE_TRAPS} traps may be active at once and "
                f"{len(state.active_traps)} are already armed. Wait for one to "
                "fire, or let an active trap do its job, before arming another."
            )
        if state.blocked_trap_name == call.name:
            return f"{call.name} cannot be re-armed as the next Warden action after it triggers"
        return None

    def arm(self, state: MatchState, call: ToolCall) -> None:
        if call.name == "watch_file":
            target = str(call.arguments["path"])
        else:
            target = str(call.arguments["process"])
        state.active_traps.append(ActiveTrap(tool_name=call.name, target=target))
        state.blocked_trap_name = None

    def matching_trap(self, state: MatchState, event: SandboxEvent) -> ActiveTrap | None:
        """The armed trap this event fires, or ``None`` if it fires nothing.

        With more than one trap armed the specific trap matters, not just that
        *a* trap fired: the Engine resolves that one and leaves the rest armed.
        """
        for trap in state.active_traps:
            if trap.tool_name == "watch_file":
                if event.path is not None and event.path == trap.target:
                    return trap
            elif (
                event.type is SandboxEventType.PROCESS_STARTED
                and event.process_name is not None
                and event.process_name == trap.target
            ):
                return trap
        return None

    def trigger(self, state: MatchState, trap: ActiveTrap) -> ActiveTrap:
        """Resolve one firing trap, freeing its slot for a later arming."""
        if trap in state.active_traps:
            state.active_traps.remove(trap)
        state.blocked_trap_name = trap.tool_name
        return trap
