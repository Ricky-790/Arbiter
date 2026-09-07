import unittest

from app.agents.models import AgentType
from app.agents.tools import ToolCall, ToolResult
from app.engine import Engine, MatchStatus
from app.sandbox.models import ChallengeSpec, SandboxEvent, SandboxEventType


class FakeSandboxManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def _record(self, operation: str, **kwargs: object) -> ToolResult:
        self.calls.append((operation, kwargs))
        return ToolResult(success=True, output=operation)

    def set_event_handler(self, match_id: str, handler: object) -> None:
        self.event_handler = (match_id, handler)

    async def get_or_create_sandbox(self, match_id: str, config: object) -> object:
        self.sandbox = (match_id, config)
        return self.sandbox

    async def destroy_sandbox(self, match_id: str) -> None:
        self.destroyed_match_id = match_id

    async def run_command(self, **kwargs: object) -> ToolResult:
        return await self._record("run_command", **kwargs)

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
            challenge=ChallengeSpec(name="test", description="test", flag="ARB{flag}"),
            sandbox_manager=manager,
        )
        return engine, manager

    async def test_start_sets_up_users_and_flag_and_initializes_credits(self) -> None:
        engine, manager = self.make_engine()

        await engine.start()

        self.assertEqual(engine.state.status, MatchStatus.RUNNING)
        self.assertEqual(engine.state.prisoner.credits, 50)
        self.assertEqual(engine.state.warden.credits, 50)
        commands = [kwargs["command"] for operation, kwargs in manager.calls if operation == "run_command"]
        self.assertTrue(any("useradd" in command and "warden" in command for command in commands))
        self.assertTrue(any("usermod -aG sudo warden" in command for command in commands))
        self.assertTrue(any("/root/secret.txt" in command and "ARB{flag}" in command for command in commands))

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
            ("run_command", {"match_id": "match-1", "command": "id", "user": "prisoner"}),
            manager.calls,
        )

    async def test_trap_overrides_warden_cooldown_and_prevents_immediate_rearm(self) -> None:
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
            ToolCall(name="submit_flag", arguments={"flag": "ARB{flag}"}),
        )

        self.assertTrue(result.success)
        self.assertEqual(engine.state.status, MatchStatus.FINISHED)
        self.assertEqual(engine.state.winner, AgentType.PRISONER)
