"""Tests for structured flag validation and verifier-script evaluation."""

import unittest

from app.agents.models import AgentType
from app.agents.tools import ToolCall, ToolResult
from app.engine import Engine, MatchStatus
from app.engine.verification import parse_verifier_verdict, validate_submission
from app.sandbox.models import ChallengeSpec


class ValidateSubmissionTests(unittest.TestCase):
    def test_empty_structure_accepts_any_dict(self) -> None:
        self.assertIsNone(validate_submission({"anything": 1}, {}))
        self.assertIsNone(validate_submission({}, None))

    def test_valid_submission_matches_structure(self) -> None:
        structure = {"success": "bool", "process_id": "str"}

        self.assertIsNone(
            validate_submission({"success": True, "process_id": "42"}, structure)
        )

    def test_non_object_submission_is_rejected(self) -> None:
        error = validate_submission("secret123", {"value": "str"})

        self.assertIsNotNone(error)
        self.assertIn("JSON object", error or "")

    def test_missing_key_is_rejected(self) -> None:
        error = validate_submission({"success": True}, {"success": "bool", "process_id": "str"})

        self.assertIn("missing required key", error or "")
        self.assertIn("process_id", error or "")

    def test_unexpected_key_is_rejected(self) -> None:
        error = validate_submission(
            {"value": "x", "extra": 1}, {"value": "str"}
        )

        self.assertIn("unexpected key", error or "")

    def test_wrong_type_is_rejected(self) -> None:
        error = validate_submission({"value": 5}, {"value": "str"})

        self.assertIn("must be of type", error or "")

    def test_bool_is_not_accepted_as_int(self) -> None:
        self.assertIsNotNone(validate_submission({"count": True}, {"count": "int"}))
        self.assertIsNone(validate_submission({"count": 3}, {"count": "int"}))

    def test_int_is_accepted_as_number(self) -> None:
        self.assertIsNone(validate_submission({"ratio": 1}, {"ratio": "number"}))

    def test_unknown_descriptor_does_not_constrain(self) -> None:
        self.assertIsNone(validate_submission({"blob": object()}, {"blob": "whatever"}))


class ParseVerifierVerdictTests(unittest.TestCase):
    def test_success_verdict(self) -> None:
        success, reason = parse_verifier_verdict(
            output='{"success": true, "reason": "process gone"}',
            exit_code=0,
            error=None,
        )

        self.assertTrue(success)
        self.assertEqual(reason, "process gone")

    def test_failure_verdict(self) -> None:
        success, reason = parse_verifier_verdict(
            output='{"success": false, "reason": "still running"}',
            exit_code=0,
            error=None,
        )

        self.assertFalse(success)
        self.assertEqual(reason, "still running")

    def test_verdict_without_reason_gets_default(self) -> None:
        success, reason = parse_verifier_verdict(
            output='{"success": true}', exit_code=0, error=None
        )

        self.assertTrue(success)
        self.assertIn("accepted", reason)

    def test_invalid_json_fails_closed(self) -> None:
        success, reason = parse_verifier_verdict(
            output="not json", exit_code=0, error=None
        )

        self.assertFalse(success)
        self.assertIn("JSON object", reason)

    def test_no_output_fails_closed_with_diagnostic(self) -> None:
        success, reason = parse_verifier_verdict(
            output="", exit_code=1, error="pgrep: not found"
        )

        self.assertFalse(success)
        self.assertEqual(reason, "pgrep: not found")


class FakeSandboxManager:
    def __init__(self, verifier_output: str = "") -> None:
        self.verifier_output = verifier_output
        self.commands: list[str] = []

    async def get_or_create_sandbox(
        self,
        match_id: str,
        config: object,
        *,
        from_snapshot: str | None = None,
    ) -> object:
        return object()

    def set_event_handler(self, match_id: str, handler: object) -> None:
        pass

    async def destroy_sandbox(self, match_id: str) -> None:
        pass

    async def run_command(self, *, match_id: str, command: str, user: str) -> ToolResult:
        self.commands.append(command)
        if "ARBITER_SUBMITTED_FLAG" in command:
            return ToolResult(success=True, output=self.verifier_output)
        return ToolResult(success=True, output="ok")


def make_verifier_engine(verifier_output: str) -> tuple[Engine, FakeSandboxManager]:
    manager = FakeSandboxManager(verifier_output)
    engine = Engine(
        match_id="match-verifier",
        challenge=ChallengeSpec(
            name="Stop the process",
            description="Stop process 42",
            flag={"success": True, "process_id": "42"},
            flag_structure={"success": "bool", "process_id": "str"},
            verifier_script="pgrep -f target",
        ),
        sandbox_manager=manager,  # type: ignore[arg-type]
    )
    return engine, manager


class EngineVerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_verifier_acceptance_wins_the_match(self) -> None:
        engine, manager = make_verifier_engine('{"success": true, "reason": "process gone"}')
        await engine.start()

        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(
                name="submit_flag",
                arguments={"response": {"success": True, "process_id": "42"}},
            ),
        )

        self.assertTrue(result.success)
        self.assertEqual(engine.state.status, MatchStatus.FINISHED)
        self.assertEqual(engine.state.winner, AgentType.PRISONER)
        self.assertEqual(
            engine.state.submitted_flag, {"success": True, "process_id": "42"}
        )
        self.assertTrue(
            any("ARBITER_SUBMITTED_FLAG" in command for command in manager.commands)
        )

    async def test_verifier_rejection_does_not_finish_the_match(self) -> None:
        engine, _ = make_verifier_engine(
            '{"success": false, "reason": "process 42 still running"}'
        )
        await engine.start()

        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(
                name="submit_flag",
                arguments={"response": {"success": True, "process_id": "42"}},
            ),
        )

        self.assertFalse(result.success)
        self.assertIn("still running", result.error or "")
        self.assertIsNone(engine.state.winner)
        self.assertEqual(engine.state.status, MatchStatus.RUNNING)

    async def test_verifier_is_not_run_for_malformed_submission(self) -> None:
        engine, manager = make_verifier_engine('{"success": true}')
        await engine.start()

        result = await engine.execute_tool_call(
            AgentType.PRISONER,
            ToolCall(
                name="submit_flag",
                arguments={"response": {"success": True}},
            ),
        )

        self.assertFalse(result.success)
        self.assertIn("missing required key", result.error or "")
        self.assertFalse(
            any("ARBITER_SUBMITTED_FLAG" in command for command in manager.commands)
        )


if __name__ == "__main__":
    unittest.main()
