import unittest

from app.agents.base import ToolChoosingAgent
from app.agents.prisoner import PrisonerAgent
from app.agents.tools.models import ToolCall
from app.agents.warden import WardenAgent


def make_agent() -> ToolChoosingAgent:
    return ToolChoosingAgent(
        model_name="gemini-3.1-flash-lite",
        instructions="test",
        allowed_tools={
            "bash",
            "read_file",
            "write_file",
            "write_to_scratchpad",
            "watch_file",
            "watch_process",
            "kill_process",
            "auto_kill",
            "block_network",
            "submit_flag",
            "pass",
        },
    )


class ToolArgumentValidationTests(unittest.TestCase):
    def test_valid_calls_pass_through_unchanged(self) -> None:
        prisoner = PrisonerAgent()
        call = prisoner._validate(
            ToolCall(name="bash", arguments={"command": "ls -la /"})
        )
        self.assertEqual(call.arguments, {"command": "ls -la /"})

        warden = WardenAgent()
        call = warden._validate(ToolCall(name="block_network", arguments={}))
        self.assertEqual(call.arguments, {})

    def test_missing_required_argument_is_rejected(self) -> None:
        agent = make_agent()
        with self.assertRaisesRegex(ValueError, "command"):
            agent._validate(ToolCall(name="bash", arguments={}))
        with self.assertRaisesRegex(ValueError, "content"):
            agent._validate(
                ToolCall(name="write_file", arguments={"path": "/tmp/x"})
            )

    def test_unexpected_argument_is_rejected(self) -> None:
        prisoner = PrisonerAgent()
        with self.assertRaisesRegex(ValueError, "invalid arguments"):
            prisoner._validate(
                ToolCall(name="pass", arguments={"reason": "tired"})
            )

    def test_disallowed_tool_name_still_rejected(self) -> None:
        prisoner = PrisonerAgent()
        with self.assertRaisesRegex(ValueError, "unavailable tool"):
            prisoner._validate(
                ToolCall(name="kill_process", arguments={"pid": 12})
            )

    def test_wrong_types_are_coerced_leniently(self) -> None:
        warden = WardenAgent()
        call = warden._validate(
            ToolCall(name="kill_process", arguments={"pid": "12"})
        )
        self.assertEqual(call.arguments, {"pid": 12})
        call = warden._validate(
            ToolCall(name="kill_process", arguments={"pid": 12.0})
        )
        self.assertEqual(call.arguments, {"pid": 12})

    def test_uncoercible_type_is_rejected(self) -> None:
        warden = WardenAgent()
        with self.assertRaisesRegex(ValueError, "pid"):
            warden._validate(
                ToolCall(name="kill_process", arguments={"pid": "abc"})
            )
        with self.assertRaisesRegex(ValueError, "pid"):
            warden._validate(
                ToolCall(name="kill_process", arguments={"pid": True})
            )

    def test_optional_union_arguments_accept_none(self) -> None:
        warden = WardenAgent()
        call = warden._validate(
            ToolCall(
                name="block_network",
                arguments={"ip": None, "port": "443"},
            )
        )
        self.assertEqual(call.arguments, {"ip": None, "port": 443})


if __name__ == "__main__":
    unittest.main()
