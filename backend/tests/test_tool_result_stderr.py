"""stderr reaches the model and the archive, even on a "successful" command.

A shell runs every line of a script regardless of earlier failures, so a
command's exit code -- and therefore ``success`` -- comes from its last line.
The run that motivated this was a Warden doing ``sudo rm ...; ls ...
``: the refused ``sudo`` failed, the trailing ``ls`` succeeded, and the result
was green with the stderr discarded. These pin that the stderr now survives, at
every hop from ``SandboxManager`` to the model to the persisted event.
"""

import unittest
from unittest.mock import AsyncMock, patch

from app.agents.models import AgentType
from app.agents.tools import ToolCall, ToolResult
from app.engine import Engine
from app.engine.engine import PRISONER_BASH_OUTPUT_CHARS
from app.sandbox.models import ChallengeSpec

STDERR = (
    "sudo: a terminal is required to read the password; sudo: a password is required\n"
)


class FakeSandboxManager:
    """A sandbox whose commands report stderr on an otherwise clean exit."""

    def __init__(self, *, stderr: str = STDERR) -> None:
        self.stderr = stderr

    def set_event_handler(self, match_id: str, handler: object) -> None:
        pass

    async def get_or_create_sandbox(
        self, match_id: str, config: object, *, from_snapshot: str | None = None
    ) -> object:
        return object()

    async def destroy_sandbox(self, match_id: str) -> None:
        pass

    async def run_command(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="ok", stderr=self.stderr or None)

    async def read_file(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="")


class StderrVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def make_engine(
        self, manager: FakeSandboxManager, *, hosted: bool = False
    ) -> Engine:
        engine = Engine(
            match_id="match-stderr",
            challenge=ChallengeSpec(name="t", description="t"),
            sandbox_manager=manager,  # type: ignore[arg-type]
            cooldown_seconds=0,
            match_metadata={"challenge_id": "t"} if hosted else None,
        )
        await engine.start()
        return engine

    async def test_the_engine_keeps_stderr_on_a_successful_call(self) -> None:
        engine = await self.make_engine(FakeSandboxManager())

        result = await engine.execute_tool_call(
            AgentType.WARDEN, ToolCall(name="bash", arguments={"command": "ls"})
        )

        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(result.stderr, STDERR)

    async def test_the_model_reads_stderr(self) -> None:
        engine = await self.make_engine(FakeSandboxManager())

        returned = await engine._execute_deferred_tool(
            AgentType.WARDEN, ToolCall(name="bash", arguments={"command": "ls"})
        )

        self.assertEqual(returned.return_value["stderr"], STDERR)
        self.assertTrue(returned.return_value["success"])

    async def test_the_persisted_event_carries_stderr(self) -> None:
        engine = await self.make_engine(FakeSandboxManager(), hosted=True)
        recorder = AsyncMock()

        with patch("app.engine.engine.store_match_activity", recorder):
            await engine.execute_tool_call(
                AgentType.WARDEN, ToolCall(name="bash", arguments={"command": "ls"})
            )

        rows = [
            call.kwargs
            for call in recorder.await_args_list
            if call.kwargs.get("event_type") == "tool_call"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"]["stderr"], STDERR)
        self.assertTrue(rows[0]["result"]["success"])

    async def test_a_clean_command_has_no_stderr_field(self) -> None:
        engine = await self.make_engine(FakeSandboxManager(stderr=""))

        returned = await engine._execute_deferred_tool(
            AgentType.WARDEN, ToolCall(name="bash", arguments={"command": "ls"})
        )

        # ``model_dump(exclude_none=True)`` drops it, so the model does not see
        # an empty field on every ordinary call.
        self.assertNotIn("stderr", returned.return_value)

    async def test_the_prisoner_bash_cap_bounds_stderr_too(self) -> None:
        long_stderr = "e" * (PRISONER_BASH_OUTPUT_CHARS + 50)
        engine = await self.make_engine(FakeSandboxManager(stderr=long_stderr))

        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "ls"})
        )

        self.assertLessEqual(len(result.stderr or ""), PRISONER_BASH_OUTPUT_CHARS + 80)
        self.assertIn("output truncated", result.stderr or "")
        self.assertTrue(result.notice)
        self.assertTrue(result.metadata["output_truncated"])
        # stderr was cut, and the count is the stderr's own, not doubled by the
        # ``error`` mirror of it (this call had ``error is None``).
        self.assertEqual(result.metadata["output_chars_dropped"], 50)

    async def test_the_warden_is_not_capped(self) -> None:
        long_stderr = "e" * (PRISONER_BASH_OUTPUT_CHARS + 50)
        engine = await self.make_engine(FakeSandboxManager(stderr=long_stderr))

        result = await engine.execute_tool_call(
            AgentType.WARDEN, ToolCall(name="bash", arguments={"command": "ls"})
        )

        self.assertEqual(len(result.stderr or ""), len(long_stderr))
        self.assertFalse(result.metadata.get("output_truncated", False))


if __name__ == "__main__":
    unittest.main()
