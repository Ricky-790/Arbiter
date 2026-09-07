import unittest

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

    async def create(self, *, config: SandboxConfig) -> FakeSandbox:
        self.config = config
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


class SandboxManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manager_creates_tracks_and_executes_in_the_correct_sandbox(self) -> None:
        client = FakeSolariClient()
        manager = SandboxManager(client=client)  # type: ignore[arg-type]

        sandbox = await manager.create_new_sandbox("match-a")
        result = await manager.run_command(
            match_id="match-a", command="id", user="prisoner"
        )

        self.assertIs(sandbox, client.sandbox)
        self.assertTrue(result.success)
        self.assertEqual(result.output, "done")
        self.assertEqual(
            client.commands,
            [{"sandbox": sandbox, "command": "id", "user": "prisoner"}],
        )

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
