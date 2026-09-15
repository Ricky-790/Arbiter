import json
import os
import unittest

from app.agents.models import AgentType
from app.agents.prisoner import PrisonerAgent
from app.agents.tools.models import ToolCall, ToolResult
from app.engine import Engine
from app.sandbox.models import ChallengeSpec


class AgentMemoryTests(unittest.TestCase):
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

    def test_long_outputs_are_never_hidden(self) -> None:
        agent = PrisonerAgent()
        big = "line " + "x " * 200
        call = ToolCall(name="bash", arguments={"command": "ls -la /"}, reason="r")
        result = ToolResult(
            success=True,
            output=big,
            exit_code=0,
            notice="long output suggestion",
        )
        import asyncio

        asyncio.run(agent.observe_result(call, result))
        asyncio.run(
            agent.observe_result(
                ToolCall(name="pass", arguments={}, reason="done"),
                ToolResult(success=True, output="ok"),
            )
        )
        entries = [json.loads(e) for e in agent._format_recent_observations()]
        # Full output retained even after aging out of most-recent.
        self.assertIn("x x x", entries[0]["tool_result"]["output"])
        self.assertEqual(
            entries[0]["tool_result"]["notice"], "long output suggestion"
        )
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


class LongOutputNoticeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._env = dict(os.environ)
        os.environ["LOWER_TOKEN_LIMIT"] = "50"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    async def test_long_output_sent_full_with_scratchpad_suggestion(self) -> None:
        engine = Engine(
            match_id="m-long",
            challenge=ChallengeSpec(name="t", description="t", flag="F"),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
        )
        await engine.start()
        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(name="bash", arguments={"command": "ls -la /"}, reason="r"),
        )
        self.assertTrue(result.success)
        # Never hidden: full output still present...
        self.assertIn("y y y", result.output)
        # ...with a scratchpad suggestion attached.
        self.assertIsNotNone(result.notice)
        self.assertIn("scratchpad", result.notice or "")


if __name__ == "__main__":
    unittest.main()
