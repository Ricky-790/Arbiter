import unittest

from app.agents.models import AgentType
from app.agents.tools import BashTool, ToolResult, build_default_registry


class RecordingContext:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def _result(self, name: str, **kwargs: object) -> ToolResult:
        self.calls.append((name, kwargs))
        return ToolResult(success=True, output=name)

    async def run_command(self, *, command: str) -> ToolResult:
        return await self._result("run_command", command=command)

    async def read_file(self, *, path: str) -> ToolResult:
        return await self._result("read_file", path=path)

    async def write_file(self, *, path: str, content: str) -> ToolResult:
        return await self._result("write_file", path=path, content=content)

    async def write_to_scratchpad(self, *, content: str) -> ToolResult:
        return await self._result("write_to_scratchpad", content=content)

    async def watch_file(self, *, path: str) -> ToolResult:
        return await self._result("watch_file", path=path)

    async def watch_process(self, *, process: str) -> ToolResult:
        return await self._result("watch_process", process=process)

    async def kill_process(self, *, pid: int) -> ToolResult:
        return await self._result("kill_process", pid=pid)

    async def auto_kill(self, *, process: str) -> ToolResult:
        return await self._result("auto_kill", process=process)

    async def block_network(
        self, *, ip: str | None = None, port: int | None = None
    ) -> ToolResult:
        return await self._result("block_network", ip=ip, port=port)

    async def submit_flag(self, *, flag: str) -> ToolResult:
        return await self._result("submit_flag", flag=flag)

    async def pass_turn(self) -> ToolResult:
        return await self._result("pass_turn")


class ToolRegistryTests(unittest.TestCase):
    def test_default_registry_exposes_only_authorized_tools(self) -> None:
        registry = build_default_registry()

        self.assertEqual(
            {tool.name for tool in registry.get_for_agent(AgentType.PRISONER)},
            {"bash", "read_file", "write_file", "write_to_scratchpad", "submit_flag", "pass"},
        )
        self.assertEqual(
            {tool.name for tool in registry.get_for_agent(AgentType.WARDEN)},
            {
                "bash",
                "read_file",
                "write_file",
                "write_to_scratchpad",
                "watch_file",
                "watch_process",
                "kill_process",
                "auto_kill",
                "block_network",
                "pass",
            },
        )

    def test_registry_rejects_duplicate_names(self) -> None:
        registry = build_default_registry()

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(BashTool())


class ToolDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bash_forwards_arbitrary_command_without_inspection(self) -> None:
        context = RecordingContext()
        command = "sudo rm -rf /tmp/example && python3 exploit.py"

        result = await BashTool().execute(context, command=command)

        self.assertTrue(result.success)
        self.assertEqual(context.calls, [("run_command", {"command": command})])

    async def test_system_and_defensive_tools_delegate_to_context(self) -> None:
        context = RecordingContext()
        registry = build_default_registry()

        self.assertTrue(
            (await registry.get("submit_flag").execute(context, flag="ARB{candidate}")).success
        )
        self.assertTrue(
            (await registry.get("watch_file").execute(context, path="/tmp/secret")).success
        )
        self.assertTrue((await registry.get("kill_process").execute(context, pid=12)).success)
        self.assertTrue(
            (await registry.get("block_network").execute(context, ip="10.0.0.1", port=443)).success
        )
        self.assertTrue((await registry.get("pass").execute(context)).success)

        self.assertEqual(
            context.calls,
            [
                ("submit_flag", {"flag": "ARB{candidate}"}),
                ("watch_file", {"path": "/tmp/secret"}),
                ("kill_process", {"pid": 12}),
                ("block_network", {"ip": "10.0.0.1", "port": 443}),
                ("pass_turn", {}),
            ],
        )
