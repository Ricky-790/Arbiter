import asyncio
import unittest

from solari_core import ConcurrencyLimitError

from app.agents.base import AgentUnavailableError
from app.agents.models import AgentType
from app.agents.tools import ToolCall, ToolResult
from app.engine import Engine, MatchStatus
from app.engine.engine import WARDEN_SUDOERS_PATH
from app.sandbox.models import ChallengeSpec, SandboxEvent, SandboxEventType


class FakeSandboxManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def _record(self, operation: str, **kwargs: object) -> ToolResult:
        self.calls.append((operation, kwargs))
        return ToolResult(success=True, output=operation)

    def set_event_handler(self, match_id: str, handler: object) -> None:
        self.event_handler = (match_id, handler)

    async def get_or_create_sandbox(
        self,
        match_id: str,
        config: object,
        *,
        from_snapshot: str | None = None,
    ) -> object:
        self.sandbox = (match_id, config)
        return self.sandbox

    async def destroy_sandbox(self, match_id: str) -> None:
        self.destroyed_match_id = match_id

    async def run_command(self, **kwargs: object) -> ToolResult:
        return await self._record("run_command", **kwargs)

    async def read_file(self, **kwargs: object) -> ToolResult:
        return await self._record("read_file", **kwargs)

    async def write_file(self, **kwargs: object) -> ToolResult:
        return await self._record("write_file", **kwargs)

    async def write_to_scratchpad(self, **kwargs: object) -> ToolResult:
        return await self._record("write_to_scratchpad", **kwargs)

    async def watch_file(self, **kwargs: object) -> ToolResult:
        return await self._record("watch_file", **kwargs)

    async def watch_process(self, **kwargs: object) -> ToolResult:
        return await self._record("watch_process", **kwargs)

    async def kill_process(self, **kwargs: object) -> ToolResult:
        return await self._record("kill_process", **kwargs)

    async def auto_kill(self, **kwargs: object) -> ToolResult:
        return await self._record("auto_kill", **kwargs)

    async def block_network(self, **kwargs: object) -> ToolResult:
        return await self._record("block_network", **kwargs)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    def make_engine(self) -> tuple[Engine, FakeSandboxManager]:
        manager = FakeSandboxManager()
        engine = Engine(
            match_id="match-1",
            challenge=ChallengeSpec(
                name="test",
                description="test",
                flag={"value": "ARB{flag}"},
                flag_structure={"value": "str"},
                files={"/root/secret.txt": "ARB{flag}"},
            ),
            sandbox_manager=manager,
        )
        return engine, manager

    async def test_start_sets_up_users_and_flag_and_initializes_credits(self) -> None:
        engine, manager = self.make_engine()

        await engine.start()

        self.assertEqual(engine.state.status, MatchStatus.RUNNING)
        self.assertEqual(engine.state.prisoner.credits, 50)
        self.assertEqual(engine.state.warden.credits, 50)
        commands = [
            kwargs["command"]
            for operation, kwargs in manager.calls
            if operation == "run_command"
        ]
        self.assertTrue(
            any("useradd" in command and "warden" in command for command in commands)
        )
        self.assertTrue(
            any("usermod -aG sudo warden" in command for command in commands)
        )
        self.assertTrue(
            any(
                "/root/secret.txt" in command and "ARB{flag}" in command
                for command in commands
            )
        )

    def test_setup_commands_own_files_and_run_setup_script(self) -> None:
        engine = Engine(
            match_id="setup-1",
            challenge=ChallengeSpec(
                name="t",
                description="t",
                flag={"value": "s"},
                flag_structure={"value": "str"},
                files={"/challenge/hidden/.secret": "s"},
                setup_script="nohup /tmp/service.sh &",
            ),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
        )

        commands = engine._setup_commands()

        self.assertTrue(any("useradd" in c and "warden" in c for c in commands))
        self.assertEqual(commands[-1], "nohup /tmp/service.sh &")

        file_commands = [c for c in commands if "/challenge/hidden/.secret" in c]
        self.assertEqual(len(file_commands), 1)
        self.assertIn("mkdir -p /challenge/hidden", file_commands[0])
        self.assertIn("chown prisoner /challenge/hidden/.secret", file_commands[0])
        self.assertIn("chmod 600 /challenge/hidden/.secret", file_commands[0])

    def test_setup_closes_the_empty_root_password_hole(self) -> None:
        """Without this both agents are root, and every other rule is moot."""
        engine = Engine(
            match_id="setup-2",
            challenge=ChallengeSpec(name="t", description="t"),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
        )

        self.assertIn("passwd -l root", engine._setup_commands())

    def test_setup_gives_the_warden_passwordless_sudo(self) -> None:
        engine = Engine(
            match_id="setup-3",
            challenge=ChallengeSpec(name="t", description="t"),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
        )

        rule = [c for c in engine._setup_commands() if WARDEN_SUDOERS_PATH in c]
        self.assertEqual(len(rule), 1)
        self.assertIn("warden ALL=(ALL) NOPASSWD:ALL", rule[0])
        self.assertIn(f"chmod 440 {WARDEN_SUDOERS_PATH}", rule[0])
        # Validated before sudo ever reads it: a bad rule must fail setup
        # rather than break sudo for the rest of the match.
        self.assertIn(f"visudo -cf {WARDEN_SUDOERS_PATH}", rule[0])

    def test_the_warden_rule_names_the_configured_warden_user(self) -> None:
        engine = Engine(
            match_id="setup-4",
            challenge=ChallengeSpec(
                name="t", description="t", warden_user="overseer"
            ),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
        )

        rule = [c for c in engine._setup_commands() if WARDEN_SUDOERS_PATH in c]
        self.assertIn("overseer ALL=(ALL) NOPASSWD:ALL", rule[0])
        self.assertNotIn("warden ALL=", rule[0])

    async def test_tool_cost_and_cooldown_are_centrally_enforced(self) -> None:
        engine, manager = self.make_engine()
        await engine.start()

        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )
        cooldown_result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )

        self.assertTrue(result.success)
        self.assertEqual(engine.state.prisoner.credits, 48)
        self.assertFalse(cooldown_result.success)
        self.assertEqual(cooldown_result.error, "Tool cooldown is active")
        self.assertIn(
            (
                "run_command",
                {"match_id": "match-1", "command": "id", "user": "prisoner"},
            ),
            manager.calls,
        )

    async def test_trap_overrides_warden_cooldown_and_prevents_immediate_rearm(
        self,
    ) -> None:
        engine, _ = self.make_engine()
        await engine.start()

        armed = await engine.execute_tool_call(
            AgentType.WARDEN,
            ToolCall(name="watch_file", arguments={"path": "/tmp/secret"}),
        )
        triggered = await engine.handle_sandbox_event(
            SandboxEvent(type=SandboxEventType.FILE_MODIFIED, path="/tmp/secret")
        )
        rearm = await engine.execute_tool_call(
            AgentType.WARDEN,
            ToolCall(name="watch_file", arguments={"path": "/tmp/secret"}),
        )
        reaction = await engine.execute_tool_call(
            AgentType.WARDEN,
            ToolCall(name="block_network", arguments={}),
        )

        self.assertTrue(armed.success)
        self.assertTrue(triggered)
        self.assertFalse(rearm.success)
        self.assertIn("cannot be re-armed", rearm.error or "")
        self.assertTrue(reaction.success)

    async def test_engine_evaluates_flag_submission_and_finishes_match(self) -> None:
        engine, _ = self.make_engine()
        await engine.start()

        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(
                name="submit_flag",
                arguments={"response": {"value": "ARB{flag}"}},
            ),
        )

        self.assertTrue(result.success)
        self.assertEqual(engine.state.status, MatchStatus.FINISHED)
        self.assertEqual(engine.state.winner, AgentType.PRISONER)

    async def test_free_tools_skip_credits_and_cooldown(self) -> None:
        engine, _ = self.make_engine()
        await engine.start()

        read = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="read_file", arguments={"path": "a.txt"})
        )
        scratch = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="write_to_scratchpad", arguments={"content": "note"}),
        )
        # A charged action immediately after is not cooldown-rejected.
        bash = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )

        self.assertTrue(read.success)
        self.assertTrue(scratch.success)
        self.assertTrue(bash.success)
        self.assertEqual(engine.state.prisoner.credits, 48)


class UnavailableSandboxManager(FakeSandboxManager):
    """Stands in for a Solari account whose only slot is still occupied."""

    async def get_or_create_sandbox(
        self,
        match_id: str,
        config: object,
        *,
        from_snapshot: str | None = None,
    ) -> object:
        raise ConcurrencyLimitError("sandbox limit reached")


class SandboxSetupFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_never_obtaining_a_sandbox_reports_its_real_error(self) -> None:
        """Cleanup after a failed setup must not hide why setup failed.

        Cleanup once looked the sandbox up and raised ``No sandbox exists for
        match``, replacing the actual reason the match could not start.
        """
        manager = UnavailableSandboxManager()
        engine = Engine(
            match_id="match-waiting",
            challenge=ChallengeSpec(
                name="test",
                description="test",
                flag={"value": "ARB{flag}"},
            ),
            sandbox_manager=manager,  # type: ignore[arg-type]
        )

        with self.assertRaises(ConcurrencyLimitError):
            await engine.run_agents(object(), object())

        self.assertEqual(manager.destroyed_match_id, "match-waiting")
        self.assertNotEqual(engine.state.status, MatchStatus.RUNNING)


class StubAgent:
    """Minimal ``AgentActionSource``; the Engine never reaches the sandbox."""

    def bind_tool_executor(self, executor: object) -> None:
        pass

    def bind_event_reporter(self, reporter: object) -> None:
        pass

    async def run_turn(self, scratchpad: str = "") -> str | None:
        await asyncio.sleep(0.01)
        return "idle"


class UnavailableAgent(StubAgent):
    """An agent whose provider stayed failing past its in-turn retry budget."""

    async def run_turn(self, scratchpad: str = "") -> str | None:
        raise AgentUnavailableError(
            "Model unavailable after 3 attempts (last status 429)"
        )


class AgentUnavailableTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unavailable_warden_ends_the_match_immediately(self) -> None:
        """Exhausted retries must stop the match, not leave it hanging."""
        manager = FakeSandboxManager()
        engine = Engine(
            match_id="match-1",
            challenge=ChallengeSpec(
                name="test",
                description="test",
                flag={"value": "ARB{flag}"},
            ),
            sandbox_manager=manager,  # type: ignore[arg-type]
        )

        await engine.run_agents(StubAgent(), UnavailableAgent())

        self.assertEqual(engine.state.status, MatchStatus.FINISHED)
        self.assertEqual(engine.state.winner, AgentType.PRISONER)
        self.assertIn("not available", engine.state.end_reason or "")
        self.assertEqual(manager.destroyed_match_id, "match-1")


class SideStatsTests(unittest.IsolatedAsyncioTestCase):
    """The end-of-match summary the reviewer reads is written from live state."""

    def make_engine(self) -> Engine:
        return Engine(
            match_id="match-stats",
            challenge=ChallengeSpec(
                name="test",
                description="test",
                flag={"value": "ARB{flag}"},
                flag_structure={"value": "str"},
            ),
            sandbox_manager=FakeSandboxManager(),
        )

    async def test_tool_calls_are_counted_per_side(self) -> None:
        engine = self.make_engine()
        await engine.start()

        await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )
        await engine.execute_tool_call(
            AgentType.WARDEN, ToolCall(name="bash", arguments={"command": "id"})
        )
        await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )

        self.assertEqual(engine.state.prisoner.tool_calls, 2)
        self.assertEqual(engine.state.warden.tool_calls, 1)

    async def test_a_replayed_call_is_not_counted(self) -> None:
        """A fork rebuild restores history; it does not make new calls."""
        engine = self.make_engine()
        await engine.start()
        engine.begin_replay()

        await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="bash", arguments={"command": "id"}),
            replay_at=engine.state.started_at,
        )

        self.assertEqual(engine.state.prisoner.tool_calls, 0)

    async def test_the_summary_carries_credits_and_tool_calls(self) -> None:
        engine = self.make_engine()
        await engine.start()

        stats = engine._side_stats(AgentType.PRISONER)

        self.assertEqual(stats["tool_calls"], 0)
        self.assertIsInstance(stats["credits"], int)

    async def test_each_side_carries_only_its_own_trap_counter(self) -> None:
        """A counter the other side owns would read as a real zero."""
        engine = self.make_engine()
        await engine.start()

        self.assertEqual(
            set(engine._side_stats(AgentType.PRISONER)),
            {"credits", "tool_calls", "times_trapped"},
        )
        self.assertEqual(
            set(engine._side_stats(AgentType.WARDEN)),
            {"credits", "tool_calls", "traps_armed", "traps_triggered"},
        )

    async def test_the_summary_is_a_plain_dict_for_jsonb(self) -> None:
        engine = self.make_engine()
        await engine.start()

        stats = engine._side_stats(AgentType.WARDEN)

        self.assertIs(type(stats), dict)
        for value in stats.values():
            self.assertIsInstance(value, int)


class TrapStatsTests(unittest.IsolatedAsyncioTestCase):
    """Trap activity is counted in the Engine, not re-derived by the reviewer."""

    def make_engine(self) -> Engine:
        return Engine(
            match_id="match-traps",
            challenge=ChallengeSpec(
                name="test",
                description="test",
                flag={"value": "ARB{flag}"},
                flag_structure={"value": "str"},
            ),
            sandbox_manager=FakeSandboxManager(),
        )

    async def arm(self, engine: Engine, process: str) -> ToolResult:
        return await engine.execute_tool_call(
            AgentType.WARDEN,
            ToolCall(name="auto_kill", arguments={"process": process}),
        )

    async def test_a_successful_arming_is_counted(self) -> None:
        engine = self.make_engine()
        await engine.start()

        await self.arm(engine, "worker")

        self.assertEqual(engine.state.warden.traps_armed, 1)

    async def test_a_rejected_arming_is_not_counted(self) -> None:
        """One trap at a time: the second call arms nothing, so it is not a trap."""
        engine = self.make_engine()
        await engine.start()
        await self.arm(engine, "worker")

        await self.arm(engine, "other")

        self.assertEqual(engine.state.warden.traps_armed, 1)

    async def test_a_firing_counts_for_both_sides(self) -> None:
        engine = self.make_engine()
        await engine.start()
        await self.arm(engine, "worker")

        fired = await engine.handle_sandbox_event(
            SandboxEvent(type=SandboxEventType.PROCESS_STARTED, process_name="worker")
        )

        self.assertTrue(fired)
        self.assertEqual(engine.state.warden.traps_triggered, 1)
        self.assertEqual(engine.state.prisoner.times_trapped, 1)

    async def test_an_unrelated_event_fires_nothing(self) -> None:
        engine = self.make_engine()
        await engine.start()
        await self.arm(engine, "worker")

        fired = await engine.handle_sandbox_event(
            SandboxEvent(
                type=SandboxEventType.PROCESS_STARTED, process_name="something-else"
            )
        )

        self.assertFalse(fired)
        self.assertEqual(engine.state.warden.traps_triggered, 0)
        self.assertEqual(engine.state.prisoner.times_trapped, 0)

    async def test_the_firing_records_its_target_and_turn(self) -> None:
        """Which trap fired, and where in the match -- not just that one did."""
        engine = self.make_engine()
        await engine.start()
        await self.arm(engine, "worker")
        engine.state.prisoner.turns = 3

        await engine.handle_sandbox_event(
            SandboxEvent(type=SandboxEventType.PROCESS_STARTED, process_name="worker")
        )

        recorded = [
            event
            for event in engine.state.events
            if event.get("type") == "trap_triggered"
        ][-1]
        self.assertEqual(recorded["trap"], "auto_kill")
        self.assertEqual(recorded["target"], "worker")
        self.assertEqual(recorded["prisoner_turn"], 3)

    async def test_each_side_is_summarised_with_its_own_traps(self) -> None:
        engine = self.make_engine()
        await engine.start()
        await self.arm(engine, "worker")
        await engine.handle_sandbox_event(
            SandboxEvent(type=SandboxEventType.PROCESS_STARTED, process_name="worker")
        )

        warden = engine._side_stats(AgentType.WARDEN)
        prisoner = engine._side_stats(AgentType.PRISONER)

        self.assertEqual(warden["traps_armed"], 1)
        self.assertEqual(warden["traps_triggered"], 1)
        # The Prisoner arms nothing, so it carries no arming counter at all.
        self.assertNotIn("traps_armed", prisoner)
        self.assertEqual(prisoner["times_trapped"], 1)
        self.assertNotIn("traps_triggered", prisoner)
