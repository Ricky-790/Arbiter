import asyncio
import unittest
from datetime import datetime, timedelta

from solari_core import ConcurrencyLimitError

from app.agents.base import AgentUnavailableError
from app.agents.models import AgentType
from app.agents.tools import (
    PRISONER_BASH_OUTPUT_CHARS,
    ToolCall,
    ToolResult,
)
from app.engine import Engine, MatchStatus
from app.engine.engine import PRISONER_OUT_OF_CREDITS, WARDEN_SUDOERS_PATH
from app.engine.models import utc_now
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
        # The challenge's own script still runs, but home isolation is appended
        # after it so nothing the challenge does can reopen a home directory.
        self.assertIn("nohup /tmp/service.sh &", commands)

        file_commands = [c for c in commands if "/challenge/hidden/.secret" in c]
        self.assertEqual(len(file_commands), 1)
        self.assertIn("mkdir -p /challenge/hidden", file_commands[0])
        self.assertIn("chown prisoner /challenge/hidden/.secret", file_commands[0])
        self.assertIn("chmod 600 /challenge/hidden/.secret", file_commands[0])

    def test_setup_isolates_each_agents_home_directory(self) -> None:
        """Mode 700 is what keeps each side out of the other's home.

        ``useradd -m`` leaves the homes world-readable, so without this the
        Prisoner could read the Warden's scratchpad -- its plan -- and the
        Warden could read the Prisoner's.
        """
        engine = Engine(
            match_id="setup-homes",
            challenge=ChallengeSpec(name="t", description="t"),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
        )

        commands = engine._setup_commands()

        lockdown = [c for c in commands if "chmod 700" in c]
        self.assertEqual(len(lockdown), 2)
        self.assertIn("/home/prisoner", lockdown[0])
        self.assertIn("chown prisoner /home/prisoner", lockdown[0])
        self.assertIn("/home/warden", lockdown[1])
        self.assertIn("chown warden /home/warden", lockdown[1])
        # Last: nothing after them may loosen a home back up.
        self.assertEqual(commands[-2:], lockdown)

    def test_home_isolation_follows_the_configured_user_names(self) -> None:
        engine = Engine(
            match_id="setup-homes-2",
            challenge=ChallengeSpec(
                name="t",
                description="t",
                prisoner_user="inmate",
                warden_user="overseer",
            ),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
        )

        commands = engine._setup_commands()

        self.assertIn("/home/inmate", " ".join(commands))
        self.assertIn("/home/overseer", " ".join(commands))
        self.assertNotIn("/home/prisoner", " ".join(commands))

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


class PrisonerOutOfCreditsTests(unittest.IsolatedAsyncioTestCase):
    """Being unable to pay for an action ends the match for the Prisoner.

    Credits are the Prisoner's budget for working on the challenge, so a
    Prisoner that cannot afford the action it just chose has nothing left to
    play with. Ending at that moment is deliberate: the alternative is the wall
    clock running out, which is the same Warden win reached by watching an agent
    that can no longer do anything.
    """

    def make_engine(self) -> Engine:
        return Engine(
            match_id="match-broke",
            challenge=ChallengeSpec(
                name="test",
                description="test",
                flag={"value": "ARB{flag}"},
                flag_structure={"value": "str"},
            ),
            sandbox_manager=FakeSandboxManager(),
            # Pacing must not be what decides whether the call reaches the
            # credit check.
            cooldown_seconds=0,
        )

    async def bash(self, engine: Engine, *, credits: int) -> ToolResult:
        engine.state.prisoner.credits = credits
        return await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )

    async def test_a_charged_tool_the_prisoner_cannot_pay_for_ends_the_match(
        self,
    ) -> None:
        engine = self.make_engine()
        await engine.start()

        result = await self.bash(engine, credits=1)  # bash costs 2

        self.assertFalse(result.success)
        self.assertEqual(engine.state.status, MatchStatus.FINISHED)
        self.assertEqual(engine.state.winner, AgentType.WARDEN)
        self.assertEqual(engine.state.end_reason, PRISONER_OUT_OF_CREDITS)

    async def test_the_finish_is_recorded_for_spectators_and_the_reviewer(
        self,
    ) -> None:
        engine = self.make_engine()
        await engine.start()

        await self.bash(engine, credits=0)

        finished = [
            event
            for event in engine.state.events
            if event.get("type") == "match_finished"
        ][-1]
        self.assertEqual(finished["end_reason"], PRISONER_OUT_OF_CREDITS)
        self.assertEqual(finished["winner"], "warden")

    async def test_an_affordable_tool_does_not_end_anything(self) -> None:
        engine = self.make_engine()
        await engine.start()

        result = await self.bash(engine, credits=2)

        self.assertTrue(result.success)
        self.assertEqual(engine.state.status, MatchStatus.RUNNING)
        self.assertEqual(engine.state.prisoner.credits, 0)

    async def test_a_free_tool_is_still_usable_with_no_credits(self) -> None:
        """Nothing to pay for means nothing to be out of."""
        engine = self.make_engine()
        await engine.start()
        engine.state.prisoner.credits = 0

        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="read_file", arguments={"path": "/challenge/README.md"}),
        )

        self.assertTrue(result.success)
        self.assertEqual(engine.state.status, MatchStatus.RUNNING)

    async def test_a_broke_prisoner_can_still_submit_a_flag(self) -> None:
        """``submit_flag`` costs nothing, so a found flag is not thrown away.

        The end only happens when the Prisoner actually reaches for something it
        cannot pay for.
        """
        engine = self.make_engine()
        await engine.start()
        engine.state.prisoner.credits = 0

        await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="submit_flag", arguments={"response": {"value": "ARB{flag}"}}),
        )

        self.assertEqual(engine.state.winner, AgentType.PRISONER)

    async def test_a_broke_warden_is_only_rejected(self) -> None:
        """The rule is the Prisoner's, and the asymmetry is intentional.

        The Warden running dry stops it acting, but it is not the side working
        against a budget to complete the challenge -- and ending the match would
        award the Prisoner a win for the Warden's spending, which is not what
        running out means for that side.
        """
        engine = self.make_engine()
        await engine.start()
        engine.state.warden.credits = 0

        result = await engine.execute_tool_call(
            AgentType.WARDEN, ToolCall(name="bash", arguments={"command": "id"})
        )

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure_category"], "insufficient_credits")
        self.assertEqual(engine.state.status, MatchStatus.RUNNING)

    async def test_a_replayed_call_cannot_end_a_fork_rebuild(self) -> None:
        """The fork worker rebuilds a sandbox through this same path.

        Finishing there would stop the *replay*: every later call would come
        back ``match_not_running`` and the snapshot would be rebuilt wrong.
        """
        engine = self.make_engine()
        await engine.start()
        engine.begin_replay()

        result = await self.bash(engine, credits=0)

        self.assertFalse(result.success)
        self.assertEqual(engine.state.status, MatchStatus.RUNNING)
        self.assertIsNone(engine.state.end_reason)


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


class PrisonerBashOutputCapTests(unittest.IsolatedAsyncioTestCase):
    """One Prisoner bash call cannot return an unbounded amount of output.

    The cap is a Prisoner-side balance rule -- chaining `cat` across several
    files otherwise dumps a whole filesystem in one charged action -- so it is
    enforced in the Engine and must not touch the Warden.
    """

    def make_engine(self) -> tuple[Engine, FakeSandboxManager]:
        manager = FakeSandboxManager()
        engine = Engine(
            match_id="match-cap",
            challenge=ChallengeSpec(
                name="test",
                description="test",
                flag={"value": "ARB{flag}"},
                flag_structure={"value": "str"},
            ),
            sandbox_manager=manager,  # type: ignore[arg-type]
        )
        return engine, manager

    def stub_output(self, manager: FakeSandboxManager, output: str) -> None:
        async def run_command(**kwargs: object) -> ToolResult:
            return ToolResult(success=True, output=output, exit_code=0)

        manager.run_command = run_command  # type: ignore[method-assign]

    async def test_the_prisoners_bash_output_is_truncated_to_the_cap(self) -> None:
        engine, manager = self.make_engine()
        await engine.start()
        self.stub_output(manager, "x" * (PRISONER_BASH_OUTPUT_CHARS + 500))

        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="bash", arguments={"command": "cat a b c d e"}),
        )

        self.assertTrue(result.success)
        self.assertLess(len(result.output), PRISONER_BASH_OUTPUT_CHARS + 200)
        # The Agent must be able to tell that what it got is incomplete.
        self.assertIn("truncated", result.output)
        self.assertIn("500 more characters", result.output)
        self.assertIn("capped", result.notice or "")

    async def test_short_prisoner_output_is_left_alone(self) -> None:
        engine, manager = self.make_engine()
        await engine.start()
        self.stub_output(manager, "total 4\ndrwxr-xr-x 2 prisoner prisoner 4096 .\n")

        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="bash", arguments={"command": "ls -la"}),
        )

        self.assertEqual(result.output, "total 4\ndrwxr-xr-x 2 prisoner prisoner 4096 .\n")
        self.assertIsNone(result.notice)

    async def test_the_wardens_bash_output_is_not_capped(self) -> None:
        engine, manager = self.make_engine()
        await engine.start()
        long_output = "y" * (PRISONER_BASH_OUTPUT_CHARS + 500)
        self.stub_output(manager, long_output)

        result = await engine.execute_tool_call(
            AgentType.WARDEN,
            ToolCall(name="bash", arguments={"command": "cat huge"}),
        )

        self.assertEqual(result.output, long_output)
        self.assertIsNone(result.notice)

    async def test_another_prisoner_tool_is_not_capped(self) -> None:
        """Only bash: read_file has its own much smaller natural bound."""
        engine, manager = self.make_engine()
        await engine.start()
        long_output = "z" * (PRISONER_BASH_OUTPUT_CHARS + 500)

        async def read_file(**kwargs: object) -> ToolResult:
            return ToolResult(success=True, output=long_output)

        manager.read_file = read_file  # type: ignore[method-assign]

        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="read_file", arguments={"path": "/challenge/big.txt"}),
        )

        self.assertEqual(result.output, long_output)


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
            # The trap limit is what these tests exercise, so pacing must not be
            # what decides whether a second or third arming lands.
            cooldown_seconds=0,
        )

    async def arm(self, engine: Engine, process: str) -> ToolResult:
        return await engine.execute_tool_call(
            AgentType.WARDEN,
            ToolCall(name="auto_kill", arguments={"process": process}),
        )

    async def watch(
        self, engine: Engine, path: str, *, at: datetime | None = None
    ) -> ToolResult:
        return await engine.execute_tool_call(
            AgentType.WARDEN,
            ToolCall(name="watch_file", arguments={"path": path}),
            replay_at=at,
        )

    async def test_two_traps_arm_under_the_real_match_cooldown(self) -> None:
        """The limit must be reachable at the pacing a real match uses.

        The tests above run with no cooldown so the trap limit alone decides.
        This one keeps the Engine's default 5s action cooldown -- what
        ``match_worker`` actually constructs -- and drives the clock with
        ``replay_at``, so it reproduces a real Warden's spacing without waiting.

        It is the regression for the live match where the Warden armed one trap
        and was refused twice against the old one-slot rule: two armings must
        land, and the third must be refused for the *limit* rather than quietly
        for cooldown, which would look identical from the outside.
        """
        engine = Engine(
            match_id="match-traps-paced",
            challenge=ChallengeSpec(
                name="test",
                description="test",
                flag={"value": "ARB{flag}"},
                flag_structure={"value": "str"},
            ),
            sandbox_manager=FakeSandboxManager(),
        )
        await engine.start()
        base = utc_now()

        # 5s cooldown, so each arming is separated by more than that.
        first = await self.watch(engine, "/tmp/a", at=base)
        second = await self.watch(engine, "/tmp/b", at=base + timedelta(seconds=6))
        third = await self.watch(engine, "/tmp/c", at=base + timedelta(seconds=12))

        self.assertTrue(first.success, first.error)
        self.assertTrue(second.success, second.error)
        self.assertFalse(third.success)
        self.assertIn("At most 2 traps", third.error or "")
        self.assertEqual(
            [trap.target for trap in engine.state.active_traps], ["/tmp/a", "/tmp/b"]
        )

    async def test_a_successful_arming_is_counted(self) -> None:
        engine = self.make_engine()
        await engine.start()

        await self.arm(engine, "worker")

        self.assertEqual(engine.state.warden.traps_armed, 1)

    async def test_two_traps_may_be_active_at_once(self) -> None:
        engine = self.make_engine()
        await engine.start()

        first = await self.arm(engine, "worker")
        second = await self.arm(engine, "backup")

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(engine.state.warden.traps_armed, 2)
        self.assertEqual(
            [trap.target for trap in engine.state.active_traps], ["worker", "backup"]
        )

    async def test_a_rejected_arming_is_not_counted(self) -> None:
        """Two traps at a time: the third call arms nothing, so it is not a trap."""
        engine = self.make_engine()
        await engine.start()
        await self.arm(engine, "worker")
        await self.arm(engine, "backup")

        rejected = await self.arm(engine, "third")

        self.assertFalse(rejected.success)
        self.assertIn("At most 2 traps", rejected.error or "")
        self.assertEqual(engine.state.warden.traps_armed, 2)
        self.assertEqual(len(engine.state.active_traps), 2)

    async def test_a_firing_frees_only_its_own_slot(self) -> None:
        """With two armed, the event resolves the trap it matched, not both."""
        engine = self.make_engine()
        await engine.start()
        await self.watch(engine, "/tmp/a")
        await self.watch(engine, "/tmp/b")

        fired = await engine.handle_sandbox_event(
            SandboxEvent(type=SandboxEventType.FILE_MODIFIED, path="/tmp/a")
        )

        self.assertTrue(fired)
        self.assertEqual(
            [trap.target for trap in engine.state.active_traps], ["/tmp/b"]
        )

    async def test_a_freed_slot_can_be_reused(self) -> None:
        engine = self.make_engine()
        await engine.start()
        await self.watch(engine, "/tmp/a")
        await self.watch(engine, "/tmp/b")
        await engine.handle_sandbox_event(
            SandboxEvent(type=SandboxEventType.FILE_MODIFIED, path="/tmp/a")
        )

        # A different trap tool, so the just-fired name being blocked does not
        # mask whether the slot itself was released.
        rearmed = await self.arm(engine, "worker")

        self.assertTrue(rearmed.success, rearmed.error)
        self.assertEqual(
            [trap.target for trap in engine.state.active_traps],
            ["/tmp/b", "worker"],
        )

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
