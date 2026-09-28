"""Agent history must always end on a resolved step.

pydantic-ai refuses to start a run whose ``message_history`` ends on
unprocessed tool calls. The deferred-tool handler sees exactly that shape --
it runs *before* the results it returns exist -- so storing that snapshot as the
conversation left a history that no later turn could use.

That failure is not transient: the Engine's turn loop retries after a failed
turn, so a poisoned history makes *every* subsequent turn fail the same way and
the agent stays wedged until the match times out. These tests pin both halves:
the trimming helper, and that a real pydantic-ai run accepts the result.
"""

import unittest
from unittest.mock import AsyncMock

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel

from app.agents.base import ToolChoosingAgent, _drop_pending_tool_calls


def user_prompt(text: str = "go") -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def tool_call(tool_call_id: str = "c1", name: str = "bash") -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=name, args={"command": "id"}, tool_call_id=tool_call_id
            )
        ]
    )


def tool_return(tool_call_id: str = "c1", name: str = "bash") -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(tool_name=name, content="uid=0", tool_call_id=tool_call_id)
        ]
    )


class DropPendingToolCallsTests(unittest.TestCase):
    def test_a_trailing_unresolved_call_is_dropped(self) -> None:
        messages = [user_prompt(), tool_call()]

        self.assertEqual(_drop_pending_tool_calls(messages), [messages[0]])

    def test_a_resolved_call_is_kept(self) -> None:
        messages = [user_prompt(), tool_call(), tool_return()]

        self.assertEqual(_drop_pending_tool_calls(messages), messages)

    def test_a_batch_with_no_results_is_dropped_whole(self) -> None:
        """The real handler-entry shape: every call in the response is pending."""
        response = ModelResponse(
            parts=[
                ToolCallPart(tool_name="bash", args={}, tool_call_id="c1"),
                ToolCallPart(tool_name="bash", args={}, tool_call_id="c2"),
            ]
        )
        messages = [user_prompt(), response]

        self.assertEqual(_drop_pending_tool_calls(messages), [messages[0]])

    def test_a_trailing_tool_return_is_left_alone(self) -> None:
        """pydantic-ai only inspects the last message, so a return ends the check.

        A half-resolved batch is odd but not rejected -- the response itself is
        no longer the tail -- so this must not be reported as a repair.
        """
        response = ModelResponse(
            parts=[
                ToolCallPart(tool_name="bash", args={}, tool_call_id="c1"),
                ToolCallPart(tool_name="bash", args={}, tool_call_id="c2"),
            ]
        )
        messages = [user_prompt(), response, tool_return("c1")]

        self.assertEqual(_drop_pending_tool_calls(messages), messages)

    def test_consecutive_unresolved_responses_are_all_dropped(self) -> None:
        messages = [user_prompt(), tool_call("c1"), tool_call("c2")]

        self.assertEqual(_drop_pending_tool_calls(messages), [messages[0]])

    def test_earlier_unresolved_calls_are_left_alone(self) -> None:
        """Only the tail matters: pydantic-ai only inspects the last message."""
        messages = [
            user_prompt(),
            tool_call("c1"),
            user_prompt("again"),
            tool_return("c9"),
        ]

        self.assertEqual(_drop_pending_tool_calls(messages), messages)

    def test_an_empty_history_stays_empty(self) -> None:
        self.assertEqual(_drop_pending_tool_calls([]), [])

    def test_the_input_list_is_not_mutated(self) -> None:
        messages = [user_prompt(), tool_call()]

        _drop_pending_tool_calls(messages)

        self.assertEqual(len(messages), 2)


def make_agent() -> ToolChoosingAgent:
    """An agent whose ``_agent`` never reaches a provider."""
    agent = ToolChoosingAgent(
        model_name="openai:gpt-4o-mini",
        instructions="test",
        allowed_tools={"bash"},
        api_key="test-key",
    )
    # The acceptance check happens before any model call, so a test model is
    # enough for both the rejection and the acceptance case.
    agent._agent = Agent(TestModel(), output_type=[str, DeferredToolRequests])
    return agent


class UsableHistoryTests(unittest.IsolatedAsyncioTestCase):
    """The repaired history must be one pydantic-ai actually accepts."""

    def make_agent(self) -> ToolChoosingAgent:
        return make_agent()

    async def test_raw_unresolved_history_is_rejected(self) -> None:
        """Proves the repaired case below is meaningful, not vacuously passing."""
        agent = self.make_agent()
        poisoned = [user_prompt(), tool_call()]

        with self.assertRaises(UserError):
            await agent._agent.run("next turn", message_history=poisoned)

    async def test_a_poisoned_history_is_repaired_and_accepted(self) -> None:
        agent = self.make_agent()
        agent._message_history = [user_prompt(), tool_call()]

        usable = agent._usable_history()

        # The agent's stored history is repaired too, so the next turn starts
        # from the same place rather than failing forever.
        self.assertEqual(len(agent._message_history or []), 1)
        await agent._agent.run("next turn", message_history=usable)

    async def test_a_healthy_history_is_untouched(self) -> None:
        agent = self.make_agent()
        agent._message_history = [user_prompt(), tool_call(), tool_return()]

        usable = agent._usable_history()

        self.assertEqual(usable, agent._message_history)
        await agent._agent.run("next turn", message_history=usable)

    async def test_a_write_after_an_unresolved_call_cannot_wedge_the_turn(self) -> None:
        """The exact reported sequence, through run_turn itself."""
        agent = self.make_agent()
        agent._tool_executor = AsyncMock(return_value={"success": True})
        # What _handle_deferred_tools used to leave behind.
        agent._message_history = [user_prompt(), tool_call()]

        # Must not raise the UserError that surfaced as `unexpected_error`.
        output = await agent.run_turn("")

        self.assertIsInstance(output, str)


if __name__ == "__main__":
    unittest.main()


class DeferredSnapshotTests(unittest.IsolatedAsyncioTestCase):
    """The snapshot site itself: what the handler stores must be resumable."""

    async def test_the_handler_snapshot_ends_on_a_resolved_step(self) -> None:
        agent = make_agent()
        agent._tool_executor = AsyncMock(return_value={"success": True})
        prompt, response = user_prompt(), tool_call("c1")

        class FakeContext:
            def __init__(self) -> None:
                # Exactly what pydantic-ai holds when the handler is invoked:
                # the response carrying the call, with no result for it yet.
                self.messages = [prompt, response]

            def enqueue(self, message: object) -> None:  # pragma: no cover
                pass

        requests = DeferredToolRequests(
            calls=[
                ToolCallPart(
                    tool_name="bash", args={"command": "id"}, tool_call_id="c1"
                )
            ]
        )

        await agent._handle_deferred_tools(FakeContext(), requests)

        # The in-flight response is gone, so the stored history is usable.
        self.assertEqual(agent._message_history, [prompt])
        self.assertEqual(_drop_pending_tool_calls(agent._message_history), [prompt])
        await agent._agent.run("next turn", message_history=agent._message_history)
