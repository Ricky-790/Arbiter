import json
import os
import unittest

from app.agents.models import AgentType
from app.agents.prisoner import PrisonerAgent
from app.agents.tokens import HIDDEN_OUTPUT_PLACEHOLDER
from app.agents.tools.models import ToolCall, ToolResult
from app.engine import Engine
from app.sandbox.models import ChallengeSpec


class AgentMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = dict(os.environ)
        os.environ["LOWER_TOKEN_LIMIT"] = "50"
        os.environ["UPPER_TOKEN_LIMIT"] = "500"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    def test_pair_json_carries_reason_and_result_fields(self) -> None:
        agent = PrisonerAgent()
        call = ToolCall(
            name="bash", arguments={"command": "ls"}, reason="list files first"
        )
        result = ToolResult(success=True, output="a.txt", exit_code=0)
        agent._observations.append((call, result))

        rendered = agent._format_recent_observations()
        self.assertEqual(len(rendered), 1)
        entry = json.loads(rendered[0])
        self.assertEqual(entry["tool_call"]["reason"], "list files first")
        self.assertEqual(entry["tool_call"]["arguments"], {"command": "ls"})
        self.assertEqual(entry["tool_result"]["output"], "a.txt")
        self.assertTrue(entry["tool_result"]["success"])
        self.assertEqual(entry["tool_result"]["exit_code"], 0)
        self.assertNotIn("notice", entry["tool_result"])

    def test_lower_tier_output_shown_once_then_field_hidden(self) -> None:
        agent = PrisonerAgent()
        big = "line " + "x " * 200  # ~200 tokens > lower (50), < upper (500)
        call = ToolCall(name="bash", arguments={"command": "ls -la /"}, reason="r")
        result = ToolResult(
            success=True,
            output=big,
            exit_code=0,
            notice="will be hidden next turn",
        )
        import asyncio

        asyncio.run(agent.observe_result(call, result))

        first = json.loads(agent._format_recent_observations()[0])
        self.assertIn("x x x", first["tool_result"]["output"])
        self.assertEqual(first["tool_result"]["notice"], "will be hidden next turn")

        small_call = ToolCall(name="pass", arguments={}, reason="done")
        asyncio.run(
            agent.observe_result(small_call, ToolResult(success=True, output="ok"))
        )
        entries = [json.loads(e) for e in agent._format_recent_observations()]
        self.assertEqual(entries[0]["tool_result"]["output"], HIDDEN_OUTPUT_PLACEHOLDER)
        # Only the oversized field is hidden; the rest survives.
        self.assertTrue(entries[0]["tool_result"]["success"])
        self.assertEqual(entries[0]["tool_result"]["exit_code"], 0)
        self.assertEqual(
            entries[0]["tool_result"]["notice"], "will be hidden next turn"
        )
        self.assertEqual(entries[0]["tool_call"]["reason"], "r")
        self.assertEqual(entries[1]["tool_result"]["output"], "ok")


class FakeSandboxManager:
    async def set_event_handler(self, match_id: str, handler: object) -> None:
        pass

    async def get_or_create_sandbox(self, match_id: str, config: object) -> object:
        return object()

    async def destroy_sandbox(self, match_id: str) -> None:
        pass

    async def run_command(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="line " + "y " * 600)


class UpperLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._env = dict(os.environ)
        os.environ["LOWER_TOKEN_LIMIT"] = "50"
        os.environ["UPPER_TOKEN_LIMIT"] = "500"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    async def test_upper_tier_output_redacted_immediately(self) -> None:
        engine = Engine(
            match_id="m-upper",
            challenge=ChallengeSpec(name="t", description="t", flag="F"),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
        )
        await engine.start()
        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="bash", arguments={"command": "ls -la /"}, reason="r"),
        )
        self.assertTrue(result.success)
        self.assertIn("redacted immediately", result.output)
        self.assertNotIn("y y y", result.output)
        self.assertIsNotNone(result.notice)
        self.assertIn("grep", result.notice or "")


if __name__ == "__main__":
    unittest.main()
