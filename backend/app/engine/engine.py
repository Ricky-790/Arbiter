from __future__ import annotations

import asyncio
import shlex
from datetime import timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.agents.models import AgentType
from app.agents.tools import ToolCall, ToolExecutionContext, ToolRegistry, ToolResult
from app.agents.tools.registry import build_default_registry
from app.logger import get_logger
from app.sandbox.manager import SandboxManager
from app.sandbox.models import ChallengeSpec, SandboxEvent

from .cooldowns import CooldownManager
from .credits import CreditManager
from .models import MatchState, MatchStatus, utc_now
from .traps import TRAP_TOOL_NAMES, TrapManager

logger = get_logger()


@runtime_checkable
class AgentActionSource(Protocol):
    async def next_tool_call(self) -> ToolCall: ...


class EngineExecutionContext(ToolExecutionContext):
    """Per-action adapter from tools to the shared sandbox manager."""

    def __init__(self, engine: Engine, actor: AgentType) -> None:
        self.engine = engine
        self.actor = actor

    @property
    def _user(self) -> str:
        challenge = self.engine.state.challenge
        return (
            challenge.prisoner_user
            if self.actor is AgentType.PRISONER
            else challenge.warden_user
        )

    async def run_command(self, *, command: str) -> ToolResult:
        return await self.engine.sandbox_manager.run_command(
            match_id=self.engine.state.match_id, command=command, user=self._user
        )

    async def read_file(self, *, path: str) -> ToolResult:
        return await self.engine.sandbox_manager.read_file(
            match_id=self.engine.state.match_id, path=path, user=self._user
        )

    async def write_file(self, *, path: str, content: str) -> ToolResult:
        return await self.engine.sandbox_manager.write_file(
            match_id=self.engine.state.match_id,
            path=path,
            content=content,
            user=self._user,
        )

    async def write_to_scratchpad(self, *, content: str) -> ToolResult:
        return await self.engine.sandbox_manager.write_to_scratchpad(
            match_id=self.engine.state.match_id, content=content, user=self._user
        )

    async def watch_file(self, *, path: str) -> ToolResult:
        return await self.engine.sandbox_manager.watch_file(
            match_id=self.engine.state.match_id, path=path
        )

    async def watch_process(self, *, process: str) -> ToolResult:
        return await self.engine.sandbox_manager.watch_process(
            match_id=self.engine.state.match_id, process=process
        )

    async def kill_process(self, *, pid: int) -> ToolResult:
        return await self.engine.sandbox_manager.kill_process(
            match_id=self.engine.state.match_id, pid=pid
        )

    async def auto_kill(self, *, process: str) -> ToolResult:
        return await self.engine.sandbox_manager.auto_kill(
            match_id=self.engine.state.match_id, process=process
        )

    async def block_network(
        self, *, ip: str | None = None, port: int | None = None
    ) -> ToolResult:
        return await self.engine.sandbox_manager.block_network(
            match_id=self.engine.state.match_id, ip=ip, port=port
        )

    async def submit_flag(self, *, flag: str) -> ToolResult:
        self.engine.state.submitted_flag = flag
        if flag == self.engine.state.challenge.flag:
            self.engine.finish(
                winner=AgentType.PRISONER, end_reason="correct flag submitted"
            )
            return ToolResult(success=True, output="Correct flag submitted.")
        return ToolResult(success=True, output="Flag submitted for evaluation.")

    async def pass_turn(self) -> ToolResult:
        return ToolResult(success=True, output="Passed.")


class Engine:
    """Owns state, timing, and validation for exactly one active match."""

    def __init__(
        self,
        *,
        match_id: str,
        challenge: ChallengeSpec,
        sandbox_manager: SandboxManager,
        registry: ToolRegistry | None = None,
        cooldown_seconds: float = 5.0,
    ) -> None:
        self.state = MatchState(match_id=match_id, challenge=challenge)
        self.sandbox_manager = sandbox_manager
        self.registry = registry or build_default_registry()
        self.credits = CreditManager()
        self.cooldowns = CooldownManager(timedelta(seconds=cooldown_seconds))
        self.traps = TrapManager()
        self._action_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        logger.info("Game engine instance initialized")

    async def start(self) -> None:
        """Set up the deterministic challenge environment through the manager."""
        if self.state.status is not MatchStatus.CREATED:
            logger.warning("Match is already started")
            raise RuntimeError("A match can only be started once")
        self.state.status = MatchStatus.SETTING_UP
        await self.sandbox_manager.get_or_create_sandbox(
            self.state.match_id, self.state.challenge.sandbox
        )
        self.sandbox_manager.set_event_handler(
            self.state.match_id, self.handle_sandbox_event
        )
        for command in self._setup_commands():
            result = await self.sandbox_manager.run_command(
                match_id=self.state.match_id, command=command, user="root"
            )
            if not result.success:
                self.state.status = MatchStatus.ERROR
                logger.error(f"Sandbox setup failed. Error: {result.error}")
                raise RuntimeError(
                    f"Sandbox setup failed: {result.error or result.output}"
                )
        self.state.status = MatchStatus.RUNNING
        self.state.started_at = utc_now()
        self._record("match_started")
        logger.info("Match is running")

    async def execute_tool_call(self, actor: AgentType, call: ToolCall) -> ToolResult:
        """Validate, charge, cool down, and delegate one agent-requested action."""
        async with self._action_lock:
            if self.state.status is not MatchStatus.RUNNING:
                logger.warning("Match not running")
                return ToolResult(success=False, error="Match is not running")
            try:
                tool = self.registry.get(call.name)
            except KeyError:
                logger.fatal(
                    f"LLM called non-existent tool. tool: {call.name}, args: {call.arguments}"
                )
                return ToolResult(success=False, error=f"Unknown tool: {call.name}")
            if not tool.is_available_to(actor):
                logger.fatal(f"Tool call fail: {actor.value} cannot use {call.name}")
                return ToolResult(
                    success=False, error=f"{actor.value} cannot use {call.name}"
                )
            if not self.cooldowns.can_act(self.state, actor):
                logger.warning(f"{actor} tool call: On Cooldown ")
                return ToolResult(success=False, error="Tool cooldown is active")
            if not self.credits.can_afford(self.state, actor, tool.cost):
                logger.warning(f"{actor} tool call: Low Credits")
                return ToolResult(success=False, error="Insufficient credits")
            if actor is AgentType.WARDEN:
                trap_error = self.traps.validate_arm(self.state, call)
                if trap_error:
                    logger.warning(f"Trap set failed: {trap_error}")
                    return ToolResult(success=False, error=trap_error)

            self.credits.deduct(self.state, actor, tool.cost)
            self.cooldowns.start(self.state, actor)
            context = EngineExecutionContext(self, actor)
            result = await tool.execute(context, **call.arguments)
            self._agent_state(actor).last_result = result
            self._record(
                "tool_result", actor=actor.value, tool=call.name, success=result.success
            )

            if actor is AgentType.WARDEN and result.success:
                if call.name in TRAP_TOOL_NAMES:
                    self.traps.arm(self.state, call)
                elif self.state.blocked_trap_name is not None:
                    self.state.blocked_trap_name = None
            return result

    async def handle_sandbox_event(self, event: SandboxEvent) -> bool:
        """Open the Warden reaction window if the active trap matches an event."""
        async with self._action_lock:
            if self.state.status is not MatchStatus.RUNNING or not self.traps.matches(
                self.state, event
            ):
                return False
            trap = self.traps.trigger(self.state)
            reaction_until = self.cooldowns.open_warden_reaction(self.state)
            self._record(
                "trap_triggered",
                trap=trap.tool_name if trap else None,
                reaction_until=reaction_until.isoformat(),
            )
            return True

    async def run_agents(
        self,
        prisoner: AgentActionSource,
        warden: AgentActionSource,  # this means class / object type does not matter as long as it implements next_tool_call() method
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        workers: list[asyncio.Task[None]] = []
        stop_waiter: asyncio.Task[bool] | None = None
        timeout_waiter: asyncio.Task[None] | None = None
        try:
            await self.start()
            workers = [
                asyncio.create_task(self._agent_loop(AgentType.PRISONER, prisoner)),
                asyncio.create_task(self._agent_loop(AgentType.WARDEN, warden)),
            ]
            stop_waiter = asyncio.create_task(self._stop_event.wait())
            timeout_waiter = (
                asyncio.create_task(asyncio.sleep(timeout_seconds))
                if timeout_seconds is not None
                else None
            )
            wait_for = [*workers, stop_waiter]
            if timeout_waiter is not None:
                wait_for.append(timeout_waiter)
            done, _ = await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)
            if timeout_waiter in done:
                self.finish(winner=AgentType.WARDEN, end_reason="match timeout")
            elif stop_waiter not in done:
                # A worker ended unexpectedly; raise exception and finish
                # the match instead of silently leaving its opponent running.
                for worker in done:
                    worker.result()
                self.finish(end_reason="agent action loop ended")
        finally:
            for task in [*workers, stop_waiter, timeout_waiter]:
                if task is None:
                    continue
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                *workers,
                *([stop_waiter] if stop_waiter is not None else []),
                *([timeout_waiter] if timeout_waiter is not None else []),
                return_exceptions=True,
            )
            if self.state.status is MatchStatus.RUNNING:
                self.finish()
            await self.sandbox_manager.destroy_sandbox(self.state.match_id)

    def finish(
        self, *, winner: AgentType | None = None, end_reason: str | None = None
    ) -> None:
        if self.state.status in {MatchStatus.FINISHED, MatchStatus.ERROR}:
            return
        self.state.status = MatchStatus.FINISHED
        self.state.ended_at = utc_now()
        self.state.winner = winner
        self.state.end_reason = end_reason
        self._stop_event.set()
        self._record(
            "match_finished",
            winner=winner.value if winner else None,
            end_reason=end_reason,
        )

    async def _agent_loop(self, actor: AgentType, source: AgentActionSource) -> None:
        while not self._stop_event.is_set():
            if not self.cooldowns.can_act(self.state, actor):
                await asyncio.sleep(0.05)
                continue
            call = await source.next_tool_call()
            logger.info(
                f"ToolCall Request[{actor}]: name={call.name} args={call.arguments}"
            )
            logger.info(f"[{actor}] - Executing Tool Call")
            result = await self.execute_tool_call(actor, call)
            observe = getattr(source, "observe_result", None)
            if observe is not None:
                logger.info(
                    f"ToolResult[{actor}]: success={result.success}, output={result.output}, error={result.error}, metadata={result.metadata}"
                )
                await observe(result)

    def _setup_commands(self) -> list[str]:
        challenge = self.state.challenge
        commands = [
            f"id -u {shlex.quote(challenge.warden_user)} >/dev/null 2>&1 || useradd -m -s /bin/bash {shlex.quote(challenge.warden_user)}",
            f"usermod -aG sudo {shlex.quote(challenge.warden_user)}",
            f"id -u {shlex.quote(challenge.prisoner_user)} >/dev/null 2>&1 || useradd -m -s /bin/bash {shlex.quote(challenge.prisoner_user)}",
        ]
        files = {"/root/secret.txt": challenge.flag, **challenge.files}
        for path, content in files.items():
            commands.append(
                "install -d -m 700 "
                f"{shlex.quote(str(Path(path).parent))} && "
                f"printf %s {shlex.quote(content)} > {shlex.quote(path)} && chmod 600 {shlex.quote(path)}"
            )
        return commands

    def _agent_state(self, actor: AgentType):
        return self.state.prisoner if actor is AgentType.PRISONER else self.state.warden

    def _record(self, event_type: str, **details: object) -> None:
        self.state.events.append(
            {"type": event_type, "timestamp": utc_now(), **details}
        )
