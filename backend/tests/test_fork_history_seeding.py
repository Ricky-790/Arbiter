"""A match started from a fork resumes its agents' conversations.

The resume path has three links and they live in three different places, so it
is worth pinning end to end rather than one link at a time:

1. ``start-from-fork`` records the fork point on the new match row
   (``parent_match_id`` / ``branch_event_id``) -- covered in ``test_byok_key_lifecycle``
   for the key handling; here it is the lineage that matters.
2. the match worker reads it back with ``load_fork_plan`` -> ``plan_resume``,
   which returns each side's conversation cut at the branch point.
3. ``Engine._seed_fork_histories`` hands those to the agents *before* the agent
   loop starts.

The third link is the one that had no coverage at all, and the one where a
mistake is invisible: an agent that starts blank looks exactly like an agent
that was sent no history, and the match runs to completion either way.
"""

import unittest
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.agents.base import ToolChoosingAgent
from app.engine.engine import Engine
from app.engine.models import ForkPlan
from app.sandbox.models import ChallengeSpec


def conversation(opening: str) -> list[dict]:
    """A resolved turn, the shape ``dump_agent_history`` produces."""
    return ModelMessagesTypeAdapter.dump_python(
        [
            ModelRequest(parts=[UserPromptPart(content=opening)]),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="bash", args={"command": "ls"}, tool_call_id="c1"
                    )
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="bash", content="shard-1", tool_call_id="c1"
                    )
                ]
            ),
        ],
        mode="json",
    )


def plan(*, prisoner=None, warden=None) -> ForkPlan:
    return ForkPlan(
        source_match_id=uuid.uuid4(),
        branch_event_id=uuid.uuid4(),
        branch_event_timestamp=datetime.now(UTC),
        snapshot_id="snap",
        prisoner_messages=prisoner,
        warden_messages=warden,
    )


def agent() -> ToolChoosingAgent:
    return ToolChoosingAgent(
        model_name="openai:gpt-4o-mini",
        api_key="test-key",
        instructions="test",
        allowed_tools={"bash"},
        scripted_calls=None,
    )


def engine() -> Engine:
    return Engine(
        match_id="match-fork",
        challenge=ChallengeSpec(name="t", description="t"),
        sandbox_manager=object(),
    )


def first_user_prompt(source: ToolChoosingAgent) -> str | None:
    for message in source.message_history():
        for part in getattr(message, "parts", ()):
            if isinstance(part, UserPromptPart):
                return str(part.content)
    return None


class ForkHistorySeedingTests(unittest.TestCase):
    def test_each_side_resumes_from_its_own_conversation(self) -> None:
        prisoner, warden = agent(), agent()

        engine()._seed_fork_histories(
            plan(
                prisoner=conversation("PRISONER-BRIEF"),
                warden=conversation("WARDEN-BRIEF"),
            ),
            prisoner,
            warden,
        )

        # The parent's opening prompt is in the agent's history, so the model
        # continues from what it already knew rather than starting blank.
        self.assertEqual(first_user_prompt(prisoner), "PRISONER-BRIEF")
        self.assertEqual(first_user_prompt(warden), "WARDEN-BRIEF")
        self.assertEqual(len(prisoner.message_history()), 3)

    def test_a_match_not_started_from_a_fork_is_left_alone(self) -> None:
        prisoner = agent()

        engine()._seed_fork_histories(None, prisoner, agent())

        self.assertEqual(prisoner.message_history(), [])

    def test_a_side_with_no_conversation_stays_blank(self) -> None:
        """One side may genuinely have had no resolved turn at the fork point."""
        prisoner, warden = agent(), agent()

        engine()._seed_fork_histories(
            plan(prisoner=conversation("PRISONER-BRIEF"), warden=None),
            prisoner,
            warden,
        )

        self.assertEqual(len(prisoner.message_history()), 3)
        self.assertEqual(warden.message_history(), [])

    def test_an_empty_conversation_is_not_seeded(self) -> None:
        prisoner = agent()

        engine()._seed_fork_histories(plan(prisoner=[], warden=[]), prisoner, agent())

        self.assertEqual(prisoner.message_history(), [])

    def test_a_source_that_keeps_no_history_is_skipped(self) -> None:
        """Scripted and test doubles have no ``load_message_history``."""

        class Scripted:
            async def run_turn(self, scratchpad: str = "") -> None:
                return None

        seeded = agent()
        # Must not raise for the double, and must still seed the real one.
        engine()._seed_fork_histories(
            plan(prisoner=conversation("BRIEF"), warden=conversation("BRIEF")),
            Scripted(),
            seeded,
        )

        self.assertEqual(len(seeded.message_history()), 3)

    def test_an_unloadable_conversation_costs_memory_not_the_match(self) -> None:
        """A bad history is swallowed, logged, and the match carries on.

        Deliberate: a fork that cannot restore one side's memory is worth less
        than a fork that refuses to run at all. The cost is that it is silent
        from the outside, which is why it is pinned here.
        """
        prisoner = agent()

        with (
            patch.object(
                ToolChoosingAgent, "load_message_history", side_effect=ValueError("bad")
            ),
            self.assertLogs("Arbiter", level="ERROR") as logged,
        ):
            engine()._seed_fork_histories(
                plan(prisoner=conversation("BRIEF"), warden=conversation("BRIEF")),
                prisoner,
                agent(),
            )

        self.assertEqual(prisoner.message_history(), [])
        self.assertTrue(
            any("Failed to seed" in line for line in logged.output),
            logged.output,
        )


if __name__ == "__main__":
    unittest.main()
