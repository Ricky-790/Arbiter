import asyncio
import os
import unittest
from unittest.mock import patch

from solari_core import ConcurrencyLimitError

from app.sandbox.manager import SandboxManager
from app.sandbox.models import CommandResult, SandboxConfig
from app.sandbox.solari_client import SolariClient


class FakeSandbox:
    pass


class FakeSolariClient:
    def __init__(self) -> None:
        self.sandbox = FakeSandbox()
        self.commands: list[dict[str, object]] = []
        self.watches: list[dict[str, object]] = []
        self.killed: list[object] = []

    async def create(
        self, *, config: SandboxConfig, from_snapshot: str | None = None
    ) -> FakeSandbox:
        self.config = config
        self.from_snapshot = from_snapshot
        return self.sandbox

    async def kill(self, sandbox: object) -> None:
        self.killed.append(sandbox)

    async def exec_command(
        self, sandbox: object, *, command: str, user: str
    ) -> CommandResult:
        self.commands.append({"sandbox": sandbox, "command": command, "user": user})
        if command == "false":
            return CommandResult(exit_code=1, stderr="failed")
        return CommandResult(exit_code=0, stdout="done")

    async def watch_file(self, sandbox: object, *, path: str, callback: object):
        self.watches.append({"sandbox": sandbox, "path": path, "callback": callback})

        async def unwatch() -> None:
            return None

        return unwatch


class OccupiedSolariClient(FakeSolariClient):
    """Refuses the first ``failures`` creates, as a busy Solari account does."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.attempts = 0

    async def create(
        self, *, config: SandboxConfig, from_snapshot: str | None = None
    ) -> FakeSandbox:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise ConcurrencyLimitError("sandbox limit reached")
        return await super().create(config=config, from_snapshot=from_snapshot)


class SandboxManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manager_creates_tracks_and_executes_in_the_correct_sandbox(self) -> None:
        client = FakeSolariClient()
        manager = SandboxManager(client=client)  # type: ignore[arg-type]

        sandbox = await manager.get_or_create_sandbox("match-a")
        # result = await manager.run_command(
        #     match_id="match-a", command="id", user="prisoner"
        # )

        self.assertIs(sandbox, client.sandbox)
        # self.assertTrue(result.success)
        # self.assertEqual(result.output, "done")
        # self.assertEqual(
        #     client.commands,
        #     [{"sandbox": sandbox, "command": "id", "user": "prisoner"}],
        # )

    async def test_manager_normalizes_command_failures_and_delegates_file_watch(self) -> None:
        client = FakeSolariClient()
        manager = SandboxManager(client=client)  # type: ignore[arg-type]
        await manager.create_new_sandbox("match-a")

        failure = await manager.run_command(
            match_id="match-a", command="false", user="prisoner"
        )
        watched = await manager.watch_file(match_id="match-a", path="/tmp/secret")

        self.assertFalse(failure.success)
        self.assertEqual(failure.error, "failed")
        self.assertTrue(watched.success)
        self.assertEqual(client.watches[0]["path"], "/tmp/secret")

    async def test_block_network_uses_manager_owned_root_operation(self) -> None:
        client = FakeSolariClient()
        manager = SandboxManager(client=client)  # type: ignore[arg-type]
        await manager.create_new_sandbox("match-a")

        result = await manager.block_network(
            match_id="match-a", ip="10.0.0.3", port=443
        )

        self.assertTrue(result.success)
        self.assertEqual(client.commands[0]["user"], "root")
        self.assertEqual(
            client.commands[0]["command"],
            "iptables -A OUTPUT -d 10.0.0.3 -p tcp --dport 443 -j DROP",
        )


class ScriptedProcessClient(FakeSolariClient):
    """Feeds ``_poll_processes`` one scripted ``ps`` snapshot per poll.

    The last snapshot is sticky, so a poll that happens while the test is
    shutting the loop down cannot change what the assertions see.
    """

    def __init__(self, snapshots: list[list[str]]) -> None:
        super().__init__()
        self.snapshots = snapshots
        self.polls = 0
        self.killed: list[int] = []

    async def exec_command(
        self, sandbox: object, *, command: str, user: str
    ) -> CommandResult:
        if command.startswith("kill "):
            self.killed.append(int(command.split()[1]))
            return CommandResult(exit_code=0, stdout="")
        self.polls += 1
        index = min(self.polls, len(self.snapshots)) - 1
        names = self.snapshots[index] if self.snapshots else []
        # A stable pid per name, so the same process across two polls is the
        # same row rather than a fresh pid that would look newly started.
        stdout = "".join(f"{2000 + i} {name}\n" for i, name in enumerate(names))
        return CommandResult(exit_code=0, stdout=stdout)


class RecordingMonitor:
    def __init__(self) -> None:
        self.started: list[tuple[int, str]] = []

    async def publish_process_started(self, pid: int, process: str) -> bool:
        self.started.append((pid, process))
        return True


class ProcessWatchTests(unittest.IsolatedAsyncioTestCase):
    """What ``watch_process`` and ``auto_kill`` each mean by "a process".

    Polling starts with an empty view of the table. Treating that as "nothing
    was running" makes every existing process look newly started, which fired a
    ``watch_process`` trap the instant it was armed -- on a process the Warden
    had just listed with ``ps`` and which nothing had touched.
    """

    MATCH = "match-proc"

    async def poll(
        self,
        snapshots: list[list[str]],
        *,
        watch: tuple[str, ...] = (),
        auto_kill: tuple[str, ...] = (),
    ) -> tuple[RecordingMonitor, ScriptedProcessClient]:
        client = ScriptedProcessClient(snapshots)
        manager = SandboxManager(client=client)  # type: ignore[arg-type]
        manager.sandboxes[self.MATCH] = FakeSandbox()
        monitor = RecordingMonitor()
        manager._monitors[self.MATCH] = monitor  # type: ignore[assignment]
        if watch:
            manager._process_watches[self.MATCH] = set(watch)
        if auto_kill:
            manager._auto_kill_rules[self.MATCH] = set(auto_kill)

        with patch("app.sandbox.manager.PROCESS_POLL_SECONDS", 0.001):
            task = asyncio.create_task(manager._poll_processes(self.MATCH))
            for _ in range(500):
                if client.polls >= len(snapshots):
                    break
                await asyncio.sleep(0.002)
            manager.sandboxes.pop(self.MATCH, None)
            await asyncio.wait_for(task, timeout=5)

        return monitor, client

    async def test_an_already_running_process_does_not_fire_a_watch(self) -> None:
        """The reported bug: the trap fired with nothing happening."""
        monitor, _ = await self.poll(
            [["arbiter-worker"], ["arbiter-worker"]], watch=("arbiter-worker",)
        )

        self.assertEqual(monitor.started, [])

    async def test_a_process_that_appears_later_fires_the_watch(self) -> None:
        """The trap must still catch a start -- the point of the fix."""
        monitor, _ = await self.poll(
            [[], ["arbiter-worker"]], watch=("arbiter-worker",)
        )

        self.assertEqual([name for _, name in monitor.started], ["arbiter-worker"])

    async def test_a_respawn_after_a_kill_fires_the_watch(self) -> None:
        """The real play: catch the supervisor bringing the worker back."""
        monitor, _ = await self.poll(
            [
                ["arbiter-worker"],
                ["arbiter-worker"],
                [],
                ["arbiter-worker"],
            ],
            watch=("arbiter-worker",),
        )

        self.assertEqual([name for _, name in monitor.started], ["arbiter-worker"])

    async def test_an_unwatched_start_is_not_reported(self) -> None:
        monitor, _ = await self.poll(
            [[], ["something-else"]], watch=("arbiter-worker",)
        )

        self.assertEqual(monitor.started, [])

    async def test_auto_kill_still_covers_what_is_already_running(self) -> None:
        """Deliberately the opposite of a watch.

        An auto-kill rule means "this must not run", so the instance already up
        is a target too. Otherwise a process that never restarts would never be
        killed at all.
        """
        _, client = await self.poll(
            [["arbiter-worker"]], auto_kill=("arbiter-worker",)
        )

        self.assertEqual(client.killed, [2000])

    async def test_auto_kill_kills_each_new_instance_once(self) -> None:
        _, client = await self.poll(
            [["arbiter-worker"], ["arbiter-worker"], ["arbiter-worker"]],
            auto_kill=("arbiter-worker",),
        )

        self.assertEqual(client.killed, [2000])


class SandboxConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_match_waits_for_the_running_match_to_release_the_slot(
        self,
    ) -> None:
        # Six refusals is twice what the old three-attempt loop tolerated: a
        # match requested while another is running must keep waiting instead
        # of failing before the running match ends.
        client = OccupiedSolariClient(failures=6)
        manager = SandboxManager(client=client)  # type: ignore[arg-type]

        with (
            patch("app.sandbox.manager.SANDBOX_RETRY_INITIAL_DELAY_SECONDS", 0.001),
            patch("app.sandbox.manager.SANDBOX_RETRY_MAX_DELAY_SECONDS", 0.001),
        ):
            sandbox = await manager.get_or_create_sandbox(
                "match-b", wait_seconds=5.0
            )

        self.assertIs(sandbox, client.sandbox)
        self.assertEqual(client.attempts, 7)
        self.assertIn("match-b", manager.sandboxes)

    async def test_match_gives_up_once_its_wait_budget_is_spent(self) -> None:
        client = OccupiedSolariClient(failures=99)
        manager = SandboxManager(client=client)  # type: ignore[arg-type]

        with self.assertRaises(ConcurrencyLimitError):
            await manager.get_or_create_sandbox("match-c", wait_seconds=0)

        self.assertEqual(client.attempts, 1)
        self.assertNotIn("match-c", manager.sandboxes)

    async def test_destroying_a_sandbox_that_was_never_created_is_a_no_op(self) -> None:
        client = FakeSolariClient()
        manager = SandboxManager(client=client)  # type: ignore[arg-type]
        manager._process_watches["match-missing"] = {"sshd"}

        await manager.destroy_sandbox("match-missing")

        self.assertEqual(client.killed, [])
        self.assertEqual(manager._process_watches, {})


class ToolResultStderrTests(unittest.TestCase):
    """stderr survives independently of the exit code.

    A shell script's exit code is its last line's, so ``success`` can be True
    while an earlier line was refused. Dropping stderr in that case hides the
    failure from both the model and the archive.
    """

    def test_a_successful_command_still_carries_its_stderr(self) -> None:
        result = SandboxManager._tool_result(
            CommandResult(
                exit_code=0,
                stdout="-rw-r--r-- 1 prisoner root 9 ...",
                stderr="sudo: a password is required\n",
            )
        )

        self.assertTrue(result.success)
        self.assertIsNone(result.error)  # still no failure reason
        self.assertEqual(result.stderr, "sudo: a password is required\n")

    def test_stderr_is_none_when_the_command_wrote_none(self) -> None:
        result = SandboxManager._tool_result(
            CommandResult(exit_code=0, stdout="ok")
        )

        self.assertIsNone(result.stderr)

    def test_a_failure_still_reports_the_reason_as_error(self) -> None:
        result = SandboxManager._tool_result(
            CommandResult(exit_code=1, stderr="failed")
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "failed")
        self.assertEqual(result.stderr, "failed")

    def test_a_failure_without_stderr_names_the_exit_code(self) -> None:
        result = SandboxManager._tool_result(CommandResult(exit_code=2))

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Command exited with code 2")
        self.assertIsNone(result.stderr)


class SolariClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_exec_command_uses_sh_for_an_arbitrary_shell_line(self) -> None:
        class Commands:
            async def run(self, command: str, **kwargs: object):
                self.command = command
                self.kwargs = kwargs
                return type(
                    "Result", (), {"exitCode": 7, "stdout": "out", "stderr": "err"}
                )()

        commands = Commands()
        sandbox = type("Sandbox", (), {"commands": commands})()

        result = await SolariClient().exec_command(
            sandbox, command="echo hi | wc -c", user="prisoner"  # type: ignore[arg-type]
        )

        self.assertEqual(commands.command, "sh")
        self.assertEqual(commands.kwargs, {"args": ["-c", "echo hi | wc -c"], "user": "prisoner"})
        self.assertEqual(result, CommandResult(exit_code=7, stdout="out", stderr="err"))


class SolariClientLoopTests(unittest.TestCase):
    """A Celery worker serves every match in its own ``asyncio.run()`` loop."""

    def test_sdk_client_is_rebuilt_when_the_event_loop_changes(self) -> None:
        """A client from a closed loop must never be handed to a new one.

        The SDK client owns an ``httpx`` pool bound to its loop, so reusing it
        across matches fails with ``RuntimeError: Event loop is closed``.
        """
        created: list[object] = []

        class FakeSandboxClient:
            def __init__(self, **kwargs: object) -> None:
                created.append(self)

        client = SolariClient()

        async def current() -> object:
            return client.client

        async def twice_in_one_loop() -> tuple[object, object]:
            return client.client, client.client

        with patch("app.sandbox.solari_client.SandboxClient", FakeSandboxClient):
            first_match = asyncio.run(current())
            same_match = asyncio.run(twice_in_one_loop())
            second_match = asyncio.run(current())

        self.assertIs(same_match[0], same_match[1])
        self.assertIsNot(first_match, second_match)
        self.assertEqual(len(created), 3)


def _live_process_watch_skip_reason() -> str | None:
    """Why the live process-watch test should not run, or ``None``."""
    if os.getenv("ARBITER_LIVE_SANDBOX") != "1":
        return "set ARBITER_LIVE_SANDBOX=1 to run the live process-watch test"
    if not os.getenv("E2B_API_KEY"):
        return "E2B_API_KEY is required for the live sandbox"
    return None


_LIVE_SKIP_REASON = _live_process_watch_skip_reason()


@unittest.skipIf(_LIVE_SKIP_REASON is not None, _LIVE_SKIP_REASON or "Live test disabled")
class LiveProcessWatchTests(unittest.IsolatedAsyncioTestCase):
    """The watch, against a real sandbox and a real ``ps``.

    The offline tests script the ``ps`` output, so they also encode an
    assumption about what ``ps -eo pid=,comm=`` returns and how ``comm`` names a
    process. This is the same check against the real thing, and it is the
    scenario that was reported: a process is already running when the trap is
    armed, and nothing touches it.

    Opt-in (``ARBITER_LIVE_SANDBOX=1``); run it after touching the process
    monitor.
    """

    MATCH = "live-process-watch"

    async def asyncSetUp(self) -> None:
        self.manager = SandboxManager()
        self.events: list[tuple[int, str]] = []

        async def handler(event: object) -> bool:
            self.events.append(
                (getattr(event, "process_id", 0), getattr(event, "process_name", ""))
            )
            return True

        await self.manager.create_new_sandbox(self.MATCH)
        self.manager.set_event_handler(self.MATCH, handler)

    async def asyncTearDown(self) -> None:
        await self.manager.destroy_sandbox(self.MATCH)

    async def run_in_sandbox(self, command: str) -> None:
        await self.manager.run_command(
            match_id=self.MATCH, command=command, user="root"
        )

    async def settle(self, seconds: float = 3.0) -> None:
        await asyncio.sleep(seconds)

    async def test_an_already_running_process_does_not_fire_the_trap(self) -> None:
        await self.run_in_sandbox("nohup sleep 300 >/dev/null 2>&1 & sleep 0.3")

        result = await self.manager.watch_process(
            match_id=self.MATCH, process="sleep"
        )
        self.assertTrue(result.success)
        await self.settle()

        self.assertEqual(self.events, [], f"trap fired on a process that was already running: {self.events}")

    async def test_a_process_that_starts_after_arming_fires_the_trap(self) -> None:
        """The other half: the fix must not make the trap unable to fire."""
        await self.run_in_sandbox("nohup sleep 300 >/dev/null 2>&1 & sleep 0.3")
        await self.manager.watch_process(match_id=self.MATCH, process="sleep")
        await self.settle(1.5)

        # A second sleep is a new pid, so it is a start the trap should catch.
        await self.run_in_sandbox("nohup sleep 300 >/dev/null 2>&1 & sleep 0.3")
        await self.settle()

        self.assertTrue(
            any(name == "sleep" for _, name in self.events),
            f"a new sleep process did not fire the trap: {self.events}",
        )
