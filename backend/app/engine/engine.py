from __future__ import annotations

import asyncio
import json
import shlex
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic_ai import ToolReturn

from app.agents.base import AgentUnavailableError
from app.agents.models import AgentType
from app.agents.tools import ToolCall, ToolExecutionContext, ToolRegistry, ToolResult
from app.agents.tools.registry import build_default_registry
from app.logger import get_logger
from app.observability import (
    agent_observability_context,
    match_span,
    output_telemetry,
    record_match_event,
    set_span_attributes,
    tool_execution_span,
)
from app.sandbox.manager import SandboxManager
from app.sandbox.models import ChallengeSpec, SandboxEvent

from .cooldowns import CooldownManager
from .credits import CreditManager
from .models import MatchState, MatchStatus, utc_now
from .traps import TRAP_TOOL_NAMES, TrapManager
from .verification import parse_verifier_verdict, validate_submission

logger = get_logger()

#: Tools exempt from credit deduction and action cooldown. File and
#: scratchpad access is free by design; everything else is budgeted.
FREE_TOOL_NAMES = frozenset({"read_file", "write_file", "write_to_scratchpad"})


@runtime_checkable
class AgentActionSource(Protocol):
    def bind_tool_executor(
        self, executor: Callable[[str, dict[str, Any]], Awaitable[Any]]
    ) -> None: ...

    async def run_turn(self, scratchpad: str = "") -> str | None: ...


class EngineExecutionContext(ToolExecutionContext):
    """Per-action adapter from tools to the shared sandbox manager."""

    def __init__(self, engine: Engine, actor: AgentType) -> None:
        self.engine = engine
        self.actor = actor

    @property
    def _user(self) -> str:
        return self.engine._sandbox_user(self.actor)

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

    async def submit_flag(self, *, response: dict[str, Any]) -> ToolResult:
        """Validate a structured submission, then judge it.

        The submission's shape is checked against the challenge's
        ``flag_structure`` first. A challenge with a ``verifier_script`` is
        judged inside the sandbox; otherwise the submission is compared with
        the stored ``flag``. The Engine alone decides the winner.
        """
        challenge = self.engine.state.challenge

        structure_error = validate_submission(response, challenge.flag_structure)
        if structure_error:
            return ToolResult(
                success=False,
                error=(
                    "Submission does not match the challenge flag structure: "
                    f"{structure_error}"
                ),
            )

        self.engine.state.submitted_flag = response

        if challenge.verifier_script:
            success, reason = await self.engine.run_verifier_script(response)
            if success:
                self.engine.finish(
                    winner=AgentType.PRISONER,
                    end_reason=f"verifier accepted the submission: {reason}",
                )
                return ToolResult(success=True, output=reason)
            return ToolResult(
                success=False, error=f"Verifier rejected the submission: {reason}"
            )

        if response == challenge.flag:
            self.engine.finish(
                winner=AgentType.PRISONER, end_reason="correct flag submitted"
            )
            return ToolResult(success=True, output="Correct flag submitted.")
        return ToolResult(
            success=False,
            error="Incorrect flag. Review the flag structure and try again.",
        )

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
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.state = MatchState(match_id=match_id, challenge=challenge)
        self.sandbox_manager = sandbox_manager
        self.registry = registry or build_default_registry()
        self.credits = CreditManager()
        self.cooldowns = CooldownManager(timedelta(seconds=cooldown_seconds))
        self.traps = TrapManager()
        # Optional live event transport (e.g. Redis pub/sub for spectators).
        # Called synchronously from `_record`; must never block or raise.
        self.event_sink = event_sink
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

    async def run_verifier_script(
        self, submission: dict[str, Any]
    ) -> tuple[bool, str]:
        """Run the challenge's in-sandbox verifier and interpret its verdict.

        The submitted answer is exposed to the script both as the
        ``ARBITER_SUBMITTED_FLAG`` environment variable (JSON) and on stdin.
        The script is expected to print ``{"success": bool, "reason": str}``;
        anything unparseable is a rejection (the Engine never guesses a win).
        """
        script = self.state.challenge.verifier_script
        if not script:
            return False, "no verifier script configured"

        payload = json.dumps(submission)
        quoted = shlex.quote(payload)
        command = (
            f"printf %s {quoted} | "
            f"ARBITER_SUBMITTED_FLAG={quoted} sh -c {shlex.quote(script)}"
        )
        result = await self.sandbox_manager.run_command(
            match_id=self.state.match_id, command=command, user="root"
        )
        return parse_verifier_verdict(
            output=result.output,
            exit_code=result.exit_code,
            error=result.error,
        )

    async def execute_tool_call(self, actor: AgentType, call: ToolCall) -> ToolResult:
        """Validate, charge, cool down, and delegate one agent-requested action.

        The tool span opens as soon as the request is received, so every
        outcome -- executed, rejected, or failed -- lands on that one span.
        """
        async with (
            self._action_lock  # Makes sure only one async task can access a shared resource
        ):
            with tool_execution_span(
                match_id=self.state.match_id,
                agent_role=actor.value,
                tool_name=call.name,
                tool_args=call.arguments,
            ) as span:
                return await self._execute_tool_call_tracked(actor, call, span)

    async def _execute_tool_call_tracked(
        self, actor: AgentType, call: ToolCall, span: Any | None
    ) -> ToolResult:
        """Validation/execution body for one tool request; span already open."""

        def reject(failure_category: str, error: str) -> ToolResult:
            set_span_attributes(
                span,
                {
                    "arbiter.status": "rejected",
                    "arbiter.success": False,
                    "arbiter.failure_category": failure_category,
                    "arbiter.credits_charged": 0,
                    **output_telemetry(None),
                },
            )
            record_match_event(
                "tool_rejected",
                match_id=self.state.match_id,
                actor=actor.value,
                tool=call.name,
                failure_category=failure_category,
                success=False,
            )
            return ToolResult(success=False, error=error)

        if self.state.status is not MatchStatus.RUNNING:
            logger.warning("Match not running")
            return reject("match_not_running", "Match is not running")
        try:
            tool = self.registry.get(call.name)
        except KeyError:
            logger.fatal(
                f"LLM called non-existent tool. tool: {call.name}, args: {call.arguments}"
            )
            return reject("tool_not_found", f"Unknown tool: {call.name}")
        if not tool.is_available_to(actor):
            logger.fatal(f"Tool call fail: {actor.value} cannot use {call.name}")
            return reject("tool_not_allowed", f"{actor.value} cannot use {call.name}")
        if not self.cooldowns.can_act(self.state, actor):
            logger.warning(f"{actor} tool call: On Cooldown ")
            return reject("cooldown", "Tool cooldown is active")
        if not self.credits.can_afford(self.state, actor, tool.cost):
            logger.warning(f"{actor} tool call: Low Credits")
            return reject("insufficient_credits", "Insufficient credits")
        if actor is AgentType.WARDEN:
            trap_error = self.traps.validate_arm(self.state, call)
            if trap_error:
                logger.warning(f"Trap set failed: {trap_error}")
                return reject("trap_blocked", trap_error)

        # Free tools (file/scratchpad access) skip budgeting entirely:
        # no credit deduction, no action cooldown.
        if call.name not in FREE_TOOL_NAMES:
            self.credits.deduct(self.state, actor, tool.cost)
            self.cooldowns.start(self.state, actor)
        context = EngineExecutionContext(self, actor)
        try:
            result = await tool.execute(context, **call.arguments)
        except Exception:
            set_span_attributes(
                span,
                {
                    "arbiter.status": "failed",
                    "arbiter.success": False,
                    "arbiter.failure_category": "execution_error",
                    "arbiter.credits_charged": tool.cost.value,
                    **output_telemetry(None),
                },
            )
            raise
        set_span_attributes(
            span,
            {
                "arbiter.status": "executed",
                "arbiter.success": result.success,
                "arbiter.exit_code": result.exit_code,
                "arbiter.credits_charged": tool.cost.value,
                **output_telemetry(result.output),
            },
        )
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
            record_match_event(
                "trap_triggered",
                match_id=self.state.match_id,
                trap=trap.tool_name if trap else None,
            )
            return True

    async def run_agents(
        self,
        prisoner: AgentActionSource,
        warden: AgentActionSource,  # this means class / object type does not matter as long as it implements run_turn() + bind_tool_executor()
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        workers: list[asyncio.Task[None]] = []
        stop_waiter: asyncio.Task[bool] | None = None
        timeout_waiter: asyncio.Task[None] | None = None
        # The match span stays open across setup, both agent tasks, all LLM
        # and tool calls, finishing, and cleanup. Tasks created inside
        # inherit its context, so the whole match lands in one trace.
        with match_span(
            match_id=self.state.match_id,
            challenge_id=self.state.challenge.name,
        ) as match_sp:
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
                done, _ = await asyncio.wait(
                    wait_for, return_when=asyncio.FIRST_COMPLETED
                )
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
            set_span_attributes(
                match_sp,
                {
                    "arbiter.status": "finished",
                    "arbiter.winner": self.state.winner.value
                    if self.state.winner
                    else None,
                    "arbiter.end_reason": self.state.end_reason,
                },
            )

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
        """Drive one actor via native deferred tool calling.

        Binds the engine's authoritative executor once, then each iteration
        is a single native ``agent.run()`` (via ``source.run_turn``) that
        resolves tool calls inline through the executor.
        """
        binder = getattr(source, "bind_tool_executor", None)
        if binder is not None:
            binder(
                lambda tool_name, args: self._execute_deferred_tool(
                    actor, tool_name, args
                )
            )
        while not self._stop_event.is_set():
            if not self.cooldowns.can_act(self.state, actor):
                await asyncio.sleep(0.05)
                continue
            scratchpad = await self._read_scratchpad(actor)
            try:
                # Agent identity for observability: covers the LLM call, the
                # deferred tool calls inside it, and the next model request.
                with agent_observability_context(agent_role=actor.value):
                    output = await source.run_turn(scratchpad)
            except asyncio.CancelledError:
                raise
            except AgentUnavailableError as unavailable:
                winner = (
                    AgentType.WARDEN
                    if actor is AgentType.PRISONER
                    else AgentType.PRISONER
                )
                end_reason = f"{actor.value} agent not available: {unavailable}"
                logger.critical(f"[{actor}] {end_reason}")
                self.finish(winner=winner, end_reason=end_reason)
                return
            except Exception:
                logger.exception(f"[{actor}] agent turn failed")
                await asyncio.sleep(1.0)
                continue
            if output:
                self._record(
                    "agent_message", actor=actor.value, content=output
                )
            if output is None:
                await asyncio.sleep(1.0)

    async def _execute_deferred_tool(
        self,
        actor: AgentType,
        tool_name: str,
        args: dict[str, Any] | None,
    ) -> Any:
        """Native deferred-tool executor: pace, execute, map.

        Waits for the actor's cooldown (preserving one-action-per-window
        pacing inside native runs), executes through the authoritative
        ``execute_tool_call`` path, and maps the engine result to a
        Pydantic AI tool return value.
        """
        while (
            not self._stop_event.is_set()
            and self.state.status is MatchStatus.RUNNING
            and not self.cooldowns.can_act(self.state, actor)
        ):
            await asyncio.sleep(0.05)
        call = ToolCall(name=tool_name, arguments=dict(args or {}))
        logger.info(
            f"ToolCall Request[{actor}]: name={call.name} args={call.arguments}"
        )
        logger.info(f"[{actor}] - Executing Tool Call")
        try:
            result = await self.execute_tool_call(actor, call)
        except Exception as error:
            logger.exception(f"[{actor}] tool execution raised")
            result = ToolResult(success=False, error=f"Tool execution failed: {error}")
        logger.info(
            f"ToolResult[{actor}]: success={result.success}, output={result.output}, error={result.error}, metadata={result.metadata}"
        )
        return ToolReturn(
            return_value=result.model_dump(exclude_none=True, exclude={"metadata"})
        )

    def _setup_commands(self) -> list[str]:
        challenge = self.state.challenge
        commands = [
            f"id -u {shlex.quote(challenge.warden_user)} >/dev/null 2>&1 || useradd -m -s /bin/bash {shlex.quote(challenge.warden_user)}",
            f"usermod -aG sudo {shlex.quote(challenge.warden_user)}",
            f"id -u {shlex.quote(challenge.prisoner_user)} >/dev/null 2>&1 || useradd -m -s /bin/bash {shlex.quote(challenge.prisoner_user)}",
        ]
        # Read-secret style challenges carry the file secret in flag["value"];
        # other challenge types (e.g. stop-process) have no file-backed secret
        # to plant, and writing the whole flag would leak the expected answer.
        files: dict[str, str] = {}
        secret = challenge.flag.get("value")
        if isinstance(secret, str):
            files["/root/secret.txt"] = secret
        files.update(challenge.files)
        for path, content in files.items():
            commands.append(
                "install -d -m 700 "
                f"{shlex.quote(str(Path(path).parent))} && "
                f"printf %s {shlex.quote(content)} > {shlex.quote(path)} && chmod 600 {shlex.quote(path)}"
            )
        return commands

    def _sandbox_user(self, actor: AgentType) -> str:
        challenge = self.state.challenge
        return (
            challenge.prisoner_user
            if actor is AgentType.PRISONER
            else challenge.warden_user
        )

    async def _read_scratchpad(self, actor: AgentType) -> str:
        """Read the actor's private scratchpad for prompt enrichment.

        Uses the sandbox manager's ``read_file`` (which resolves the path via
        ``_validate_path`` and reads as the acting user, preserving
        prisoner/warden isolation). Returns "" when the file is missing,
        empty, unreadable, or any error occurs, so a scratchpad failure can
        never break the agent loop. This is prompt enrichment, not a tool
        call: no credits or cooldowns are involved.
        """
        try:
            result = await self.sandbox_manager.read_file(
                match_id=self.state.match_id,
                path="scratchpad.txt",
                user=self._sandbox_user(actor),
            )
        except Exception:
            logger.warning(f"[{actor}] scratchpad read failed; using empty scratchpad")
            return ""
        if not result.success or not (result.output or "").strip():
            return ""
        return result.output

    def _agent_state(self, actor: AgentType):
        return self.state.prisoner if actor is AgentType.PRISONER else self.state.warden

    def _record(self, event_type: str, **details: object) -> None:
        event = {"type": event_type, "timestamp": utc_now(), **details}
        self.state.events.append(event)
        self._emit(event)

    def _emit(self, event: dict[str, Any]) -> None:
        """Hand one event to the optional live sink.

        Best-effort by design: event delivery is a side channel for
        spectators and must never affect match execution.
        """
        if self.event_sink is None:
            return
        try:
            self.event_sink(dict(event))
        except Exception:
            logger.exception("Match event sink failed")
