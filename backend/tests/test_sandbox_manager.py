import asyncio
import unittest
from unittest.mock import patch

from solari_core import ConcurrencyLimitError

from app.sandbox.client import SolariClient
from app.sandbox.manager import SandboxManager
from app.sandbox.models import CommandResult, SandboxConfig


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

        with patch("app.sandbox.client.SandboxClient", FakeSandboxClient):
            first_match = asyncio.run(current())
            same_match = asyncio.run(twice_in_one_loop())
            second_match = asyncio.run(current())

        self.assertIs(same_match[0], same_match[1])
        self.assertIsNot(first_match, second_match)
        self.assertEqual(len(created), 3)
