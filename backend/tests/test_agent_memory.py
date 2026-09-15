import os
import unittest

from app.agents.base import _build_tool_definitions
from app.agents.models import AgentType
from app.agents.tools.models import ToolCall, ToolResult
from app.engine import Engine
from app.sandbox.models import ChallengeSpec


class NativeToolDefinitionTests(unittest.TestCase):
    def test_definitions_cover_allowed_tools_with_typed_schemas(self) -> None:
        from app.agents.tools import build_default_registry

        registry = build_default_registry()
        defs = {
            d.name: d
            for d in _build_tool_definitions(
                registry, {"bash", "block_network", "pass"}
            )
        }
        self.assertEqual(set(defs), {"bash", "block_network", "pass"})
        bash_schema = defs["bash"].parameters_json_schema
        self.assertEqual(bash_schema["properties"]["command"]["type"], "string")
        self.assertIn("command", bash_schema["required"])
        block_schema = defs["block_network"].parameters_json_schema
        self.assertNotIn("ip", block_schema["required"])
        self.assertNotIn("port", block_schema["required"])
        self.assertEqual(defs["pass"].parameters_json_schema["required"], [])

    def test_unknown_allowed_names_are_skipped(self) -> None:
        from app.agents.tools import build_default_registry

        registry = build_default_registry()
        defs = _build_tool_definitions(registry, {"bash", "no_such_tool"})
        self.assertEqual([d.name for d in defs], ["bash"])


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
            ToolCall(name="bash", arguments={"command": "ls -la /"}),
        )
        self.assertTrue(result.success)
        # Never hidden: full output still present...
        self.assertIn("y y y", result.output)
        # ...with a scratchpad suggestion attached.
        self.assertIsNotNone(result.notice)
        self.assertIn("scratchpad", result.notice or "")


if __name__ == "__main__":
    unittest.main()
