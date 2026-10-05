"""Tool-call timeout: a call that never returns must not freeze the match.

Recreates the hang recorded in the match trace ``backend/a.json``. There the
Prisoner ran, as its last action::

    ln -s /bin/sleep ./arbiter-worker
    ./arbiter-worker 1000000 &
    pgrep -x arbiter-worker

The ``&`` backgrounds a decoy process without redirecting its output, so the
child kept the shell's stdout pipe open and the command runner never saw EOF.
The call ran for the remaining 355 seconds of the match, and because the action
lock is match-wide the Warden's next tool call -- queued behind it -- never ran
either. The match ended on the 600s wall-clock timeout, which is always a Warden
win.

What these tests pin is the fix: the Engine abandons a tool call that outruns
its budget, hands the agent a result it can recover from, and releases the lock
so *both* sides can take their next turn.
"""

import asyncio
import unittest

from app.agents.models import AgentType
from app.agents.tools import ToolCall, ToolResult
from app.engine import Engine, MatchStatus
from app.engine.engine import TOOL_TIMEOUT_SECONDS
from app.sandbox.models import ChallengeSpec

#: The tail of the command that hung the recorded match. The decoy process is
#: never redirected, which is what leaves the output pipe open.
HANGING_COMMAND = (
    "ln -s /bin/sleep ./arbiter-worker\n"
    "./arbiter-worker 1000000 &\n"
    "pgrep -x arbiter-worker\n"
)

#: Small enough to keep the tests instant; the production value is 45 seconds
#: and is asserted separately.
TEST_TIMEOUT = 0.05


class HangingSandbox:
    """A sandbox where the recorded hang reproduces.

    ``run_command`` never returns for the hanging command: the real cause was a
    background child holding the output pipe open, and the observable effect on
    the caller is exactly this -- no result, ever. ``hang_started`` lets a test
    know the hang is definitely in flight before it drives the other side.
    """

    def __init__(self, *, hang_log_write: bool = False) -> None:
        self.commands: list[str] = []
        self.destroyed_match_id: str | None = None
        self.hang_started = asyncio.Event()
        self.hang_log_write = hang_log_write

    def set_event_handler(self, match_id: str, handler: object) -> None:
        self.event_handler = (match_id, handler)

    async def get_or_create_sandbox(
        self, match_id: str, config: object, *, from_snapshot: str | None = None
    ) -> object:
        return (match_id, config)

    async def destroy_sandbox(self, match_id: str) -> None:
        self.destroyed_match_id = match_id

    async def run_command(self, **kwargs: object) -> ToolResult:
        command = str(kwargs.get("command", ""))
        self.commands.append(command)
        if self.hang_log_write and "Prisoner used" in command:
            # The Engine's own activity-log write, refusing to return.
            await asyncio.sleep(3600)
        # Matched exactly, not by substring: the Engine also writes the
        # Prisoner's activity log through this method, and that log line
        # quotes the command -- a substring match would hang the log write
        # instead of the tool call.
        elif command.strip() == HANGING_COMMAND.strip():
            # Stands in for "the output pipe never closes". Cancelled by the
            # Engine's timeout, which is the behaviour under test.
            self.hang_started.set()
            await asyncio.sleep(3600)
        return ToolResult(success=True, output=f"ran: {command}")

    async def read_file(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="")

    async def write_file(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="written")

    async def write_to_scratchpad(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="noted")

    async def watch_file(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="Watching")

    async def watch_process(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="Watching")

    async def kill_process(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="killed")

    async def auto_kill(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="Auto-kill rule armed")

    async def block_network(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="blocked")


class Completion:
    """Ends the match once every scripted agent has run out of turns.

    Without it the agent loops spin until the match wall clock, which would
    make every test wait for its own timeout to expire.
    """

    def __init__(self, engine: Engine, expected: int) -> None:
        self._engine = engine
        self._expected = expected
        self._done = 0

    def finished(self, name: str) -> None:
        self._done += 1
        if self._done >= self._expected:
            self._engine.finish(end_reason="scripted agents finished")


class ScriptedAgent:
    """An agent that issues a fixed list of tool calls, one batch per turn.

    ``gate`` blocks the first turn until it is set, which is how a test makes
    one side queue behind the other deterministically instead of racing it.
    """

    def __init__(
        self,
        name: str,
        turns: list[list[ToolCall]],
        *,
        completion: Completion,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.name = name
        self._turns = turns
        self._completion = completion
        self._gate = gate
        self._gate_waited = False
        self._reported_done = False
        self.executor: object | None = None
        #: One entry per executed call: the call and what the Engine returned.
        self.results: list[tuple[ToolCall, dict]] = []

    def bind_tool_executor(self, executor: object) -> None:
        self.executor = executor

    def bind_event_reporter(self, reporter: object) -> None:
        pass

    async def run_turn(self, scratchpad: str = "") -> str | None:
        if not self._turns:
            # The loop keeps calling back once a plan is spent, so completion
            # is reported exactly once per agent or the match ends early.
            if not self._reported_done:
                self._reported_done = True
                self._completion.finished(self.name)
            return None
        if self._gate is not None and not self._gate_waited:
            self._gate_waited = True
            await self._gate.wait()
        for call in self._turns.pop(0):
            returned = await self.executor(call)  # type: ignore[operator]
            payload = getattr(returned, "return_value", returned)
            self.results.append((call, payload))
        return f"{self.name} acted"


def make_engine(
    manager: HangingSandbox, *, tool_timeout: float = TEST_TIMEOUT
) -> Engine:
    return Engine(
        match_id="match-hang",
        challenge=ChallengeSpec(
            name="Stop the Background Task",
            description="test",
            flag={"value": "ARB{flag}"},
            flag_structure={"value": "str"},
        ),
        sandbox_manager=manager,  # type: ignore[arg-type]
        # Pacing is irrelevant here and would only add sleeps to the test.
        cooldown_seconds=0,
        tool_timeout_seconds=tool_timeout,
    )


def bash(command: str) -> ToolCall:
    return ToolCall(name="bash", arguments={"command": command})


class HangingToolCallTests(unittest.IsolatedAsyncioTestCase):
    """The recorded match, reduced to the moves that matter."""

    async def drive(
        self,
    ) -> tuple[Engine, HangingSandbox, ScriptedAgent, ScriptedAgent]:
        """Run the scenario: prisoner hangs, then both sides carry on."""
        manager = HangingSandbox()
        engine = make_engine(manager)
        completion = Completion(engine, expected=2)

        prisoner = ScriptedAgent(
            "prisoner",
            [
                [bash(HANGING_COMMAND)],
                [bash("echo recovered")],
            ],
            completion=completion,
        )
        # The Warden only acts once the Prisoner is provably holding the action
        # lock, so its call is queued behind the hang rather than racing it.
        warden = ScriptedAgent(
            "warden",
            [
                [bash("ps aux | grep arbiter-worker")],
                [bash("echo warden ok")],
            ],
            completion=completion,
            gate=manager.hang_started,
        )

        await engine.run_agents(prisoner, warden, timeout_seconds=5.0)
        return engine, manager, prisoner, warden

    async def test_a_hung_call_is_abandoned_instead_of_ending_the_match(self) -> None:
        engine, _, prisoner, _ = await self.drive()

        hung_call, payload = prisoner.results[0]
        self.assertEqual(hung_call.arguments["command"], HANGING_COMMAND)
        self.assertFalse(payload["success"])
        self.assertIn("did not return within", payload["error"])
        # The game continues: the match was not ended by the hang.
        self.assertEqual(engine.state.status, MatchStatus.FINISHED)
        self.assertIsNone(engine.state.winner)
        self.assertEqual(engine.state.end_reason, "scripted agents finished")

    async def test_the_prisoner_takes_another_turn_after_its_call_hangs(self) -> None:
        _, _, prisoner, _ = await self.drive()

        # ``state.turns`` counts loop iterations, including the idle ones after
        # a plan is spent, so the executed calls are the honest measure.
        self.assertEqual(len(prisoner.results), 2)
        second_call, second_payload = prisoner.results[1]
        self.assertEqual(second_call.arguments["command"], "echo recovered")
        self.assertTrue(second_payload["success"])

    async def test_the_warden_is_not_frozen_by_the_prisoners_hang(self) -> None:
        """The regression that mattered: the action lock is match-wide."""
        _, _, _, warden = await self.drive()

        self.assertEqual(len(warden.results), 2)
        for call, payload in warden.results:
            self.assertTrue(payload["success"], call.arguments)
            self.assertNotIn("did not return within", payload.get("error") or "")

    async def test_the_hanging_command_is_never_recorded_as_successful(self) -> None:
        engine, _, _, _ = await self.drive()

        results = [e for e in engine.state.events if e["type"] == "tool_result"]
        hung = [e for e in results if e["tool"] == "bash" and not e["success"]]
        self.assertEqual(len(hung), 1)
        self.assertIn("did not return within", hung[0]["error"])

    async def test_a_healthy_call_is_left_alone(self) -> None:
        """Guards against the timeout being eager enough to cut real work."""
        manager = HangingSandbox()
        engine = make_engine(manager)
        completion = Completion(engine, expected=1)
        prisoner = ScriptedAgent(
            "prisoner", [[bash("echo hello")]], completion=completion
        )
        warden = ScriptedAgent("warden", [], completion=completion)

        await engine.run_agents(prisoner, warden, timeout_seconds=5.0)

        _, payload = prisoner.results[0]
        self.assertTrue(payload["success"])
        self.assertIn("ran: echo hello", payload["output"])

    async def test_arming_a_trap_is_untouched_by_the_tool_timeout(self) -> None:
        """Traps are set and forget: the call returns and monitoring is detached."""
        manager = HangingSandbox()
        engine = make_engine(manager, tool_timeout=TEST_TIMEOUT)
        await engine.start()

        result = await engine.execute_tool_call(
            AgentType.WARDEN, ToolCall(name="auto_kill", arguments={"process": "worker"})
        )

        self.assertTrue(result.success)
        self.assertEqual(engine.state.warden.traps_armed, 1)

    async def test_a_hanging_activity_log_write_does_not_wedge_the_prisoner(
        self,
    ) -> None:
        """The log write is a sandbox command too, so it is bounded as well.

        It runs before the tool call, inside the same lock, so an unresponsive
        write would otherwise stop the Prisoner before its own call was ever
        bounded -- the same freeze, one step earlier.
        """
        manager = HangingSandbox(hang_log_write=True)
        engine = make_engine(manager)
        completion = Completion(engine, expected=2)
        prisoner = ScriptedAgent(
            "prisoner",
            [[bash("echo one")], [bash("echo two")]],
            completion=completion,
        )
        warden = ScriptedAgent("warden", [], completion=completion)

        await engine.run_agents(prisoner, warden, timeout_seconds=5.0)

        self.assertEqual(len(prisoner.results), 2)
        for call, payload in prisoner.results:
            self.assertTrue(payload["success"], call.arguments)
        # The log write was attempted and abandoned, not skipped.
        self.assertTrue(
            any("Prisoner used" in command for command in manager.commands)
        )


class TimeoutResultTests(unittest.TestCase):
    def test_the_budget_is_forty_five_seconds(self) -> None:
        self.assertEqual(TOOL_TIMEOUT_SECONDS, 45.0)

    def test_the_agent_is_told_what_happened_and_how_to_recover(self) -> None:
        engine = make_engine(HangingSandbox())

        result = engine._timed_out(ToolCall(name="bash", arguments={}))

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure_category"], "timeout")
        # The message has to work as an instruction, not just a diagnosis.
        self.assertIn("match is still running", result.error or "")
        self.assertIn("Do not repeat it unchanged", result.error or "")
        self.assertIn("may still be running in the background", result.error or "")

    def test_metadata_is_not_leaked_to_the_agent(self) -> None:
        """The category is for the persisted history, not the model prompt."""
        engine = make_engine(HangingSandbox())
        result = engine._timed_out(ToolCall(name="bash", arguments={}))

        self.assertEqual(
            set(result.model_dump(exclude_none=True, exclude={"metadata"})),
            {"success", "error", "output"},
        )


if __name__ == "__main__":
    unittest.main()
