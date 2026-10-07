"""What each side is told about the credits it has left.

Credits decide what an agent can do, and for the Prisoner they are final: a call
it cannot afford ends the match. Two things make that economy playable: the
price on every tool, and a balance the agent actually sees. The balance rides on
every ``ToolResult`` -- not on the turn prompt, which is written once at the top
of a run while the agent issues tool call after tool call inside it, so a number
there would be stale from the first charge onward. These pin both halves, plus
the copy the API exposes on a ``tool_call`` event's ``result``.
"""

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.agents.base import ToolChoosingAgent, _build_tool_definitions, _cost_note
from app.agents.models import AgentType
from app.agents.strategy_reviewer import ReviewRequest, StrategyReviewerAgent
from app.agents.tools import ToolCall, ToolResult
from app.agents.tools.models import ToolCost
from app.agents.tools.registry import build_default_registry
from app.agents.tools.review_tools import (
    REVIEW_TOOL_NAMES,
    ReviewContext,
    build_review_registry,
)
from app.api.schemas.dto_models import MatchEventSchema
from app.engine import Engine, MatchStatus
from app.sandbox.models import ChallengeSpec


class FakeSandboxManager:
    """Only what the Engine reaches for on this path."""

    def set_event_handler(self, match_id: str, handler: object) -> None:
        pass

    async def get_or_create_sandbox(
        self, match_id: str, config: object, *, from_snapshot: str | None = None
    ) -> object:
        return object()

    async def destroy_sandbox(self, match_id: str) -> None:
        pass

    async def run_command(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="ok")

    async def read_file(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="")


def definitions(registry, names: set[str]) -> dict:
    return {d.name: d for d in _build_tool_definitions(registry, names)}


class ToolPriceTests(unittest.TestCase):
    """The price the model reads is derived from the cost the Engine charges."""

    def test_a_charged_tool_states_its_price(self) -> None:
        defs = definitions(build_default_registry(), {"bash"})

        self.assertTrue(defs["bash"].description.endswith("Costs 2 credits."))

    def test_a_free_tool_says_it_costs_nothing(self) -> None:
        defs = definitions(build_default_registry(), {"read_file"})

        self.assertTrue(defs["read_file"].description.endswith("Costs no credits."))

    def test_every_match_tool_states_a_price_matching_its_cost(self) -> None:
        """Derived, not hand-written: the two cannot drift apart."""
        registry = build_default_registry()
        names = {
            tool.name
            for actor in (AgentType.PRISONER, AgentType.WARDEN)
            for tool in registry.get_for_agent(actor)
        }

        for name, definition in definitions(registry, names).items():
            with self.subTest(tool=name):
                cost = int(registry.get(name).cost)
                expected = (
                    "Costs no credits." if cost == 0 else f"Costs {cost} credits."
                )
                self.assertTrue(
                    definition.description.endswith(expected),
                    f"{name} does not end with {expected!r}: {definition.description!r}",
                )

    def test_review_tools_get_no_price_line(self) -> None:
        """The reviewer's tools have no economy, so they must not claim one."""
        defs = definitions(build_review_registry(), set(REVIEW_TOOL_NAMES))

        self.assertTrue(defs)
        for name, definition in defs.items():
            with self.subTest(tool=name):
                self.assertNotIn("Costs", definition.description)

    def test_the_cost_note_is_empty_for_a_tool_without_a_cost(self) -> None:
        class NoCost:
            name = "review_tool"
            description = "read something"

        self.assertEqual(_cost_note(NoCost()), "")

    def test_the_cost_note_covers_both_shapes(self) -> None:
        class Priced:
            def __init__(self, cost: ToolCost) -> None:
                self.cost = cost

        self.assertEqual(_cost_note(Priced(ToolCost.BASH)), "Costs 2 credits.")
        self.assertEqual(_cost_note(Priced(ToolCost.SUBMIT_FLAG)), "Costs no credits.")


class TurnPromptTests(unittest.TestCase):
    """The balance is deliberately not in the prompt any more."""

    def agent(self) -> ToolChoosingAgent:
        return ToolChoosingAgent(
            model_name="openai:gpt-4o-mini",
            api_key="test-key",
            instructions="test",
            allowed_tools={"bash"},
            objective="win",
            scripted_calls=None,
        )

    def test_the_prompt_no_longer_carries_a_balance(self) -> None:
        prompt = self.agent()._turn_prompt("notes")

        self.assertNotIn("Credits remaining", prompt)
        self.assertIn("Current match objective: win", prompt)
        self.assertIn("notes", prompt)

    def test_the_reviewer_prompt_is_its_own(self) -> None:
        reviewer = StrategyReviewerAgent(
            model_name="openai:gpt-4o-mini",
            request=ReviewRequest(
                side="prisoner",
                strategy="look around",
                challenge_name="The Hidden Artifact",
                challenge_description="Recover it.",
                win_condition="prisoner_submits_flag",
            ),
            context=ReviewContext(match_id=uuid4()),
            api_key="test-key",
        )

        self.assertNotIn("Credits remaining", reviewer._turn_prompt(""))


class _CreditEngineTests(unittest.IsolatedAsyncioTestCase):
    """Shared setup: a scripted-free engine whose sandbox is a stub."""

    async def make_engine(self, *, hosted: bool = False) -> Engine:
        engine = Engine(
            match_id="match-credits",
            challenge=ChallengeSpec(name="t", description="t"),
            sandbox_manager=FakeSandboxManager(),  # type: ignore[arg-type]
            cooldown_seconds=0,
            match_metadata={"challenge_id": "t"} if hosted else None,
        )
        await engine.start()
        return engine


class ToolResultCreditTests(_CreditEngineTests):
    """Every result the agent reads carries its balance, fresh."""

    async def test_a_charged_call_reports_what_is_left(self) -> None:
        engine = await self.make_engine()
        self.assertEqual(engine.state.prisoner.credits, 100)

        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )

        self.assertTrue(result.success)
        # bash costs 2, so the balance attached is the post-charge one.
        self.assertEqual(result.credits, 98)
        self.assertEqual(engine.state.prisoner.credits, 98)

    async def test_the_warden_gets_its_own_balance(self) -> None:
        engine = await self.make_engine()

        result = await engine.execute_tool_call(
            AgentType.WARDEN, ToolCall(name="bash", arguments={"command": "id"})
        )

        self.assertEqual(result.credits, 98)
        # The two economies are separate: the Prisoner spent nothing.
        self.assertEqual(engine.state.prisoner.credits, 100)

    async def test_a_free_tool_reports_the_unchanged_balance(self) -> None:
        engine = await self.make_engine()
        engine.state.prisoner.credits = 7

        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="read_file", arguments={"path": "x"})
        )

        self.assertEqual(result.credits, 7)

    async def test_a_rejection_reports_the_balance_too(self) -> None:
        """The refused call is exactly when the number matters most."""
        engine = await self.make_engine()
        engine.state.prisoner.credits = 0

        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure_category"], "insufficient_credits")
        self.assertEqual(result.credits, 0)
        self.assertEqual(engine.state.status, MatchStatus.FINISHED)

    async def test_an_unknown_tool_still_reports_the_balance(self) -> None:
        engine = await self.make_engine()
        engine.state.prisoner.credits = 41

        result = await engine.execute_tool_call(
            AgentType.PRISONER, ToolCall(name="no_such_tool")
        )

        self.assertEqual(result.metadata["failure_category"], "tool_not_found")
        self.assertEqual(result.credits, 41)

    async def test_the_model_reads_the_balance_off_the_tool_return(self) -> None:
        """The mapper must not drop the field between Engine and model."""
        engine = await self.make_engine()

        returned = await engine._execute_deferred_tool(
            AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
        )

        self.assertEqual(returned.return_value["credits"], 98)

    async def test_a_tool_result_without_an_engine_has_no_credits(self) -> None:
        """The reviewer's tools never pass through the Engine, so no field."""
        self.assertIsNone(ToolResult(success=True).credits)
        self.assertNotIn(
            "credits", ToolResult(success=True).model_dump(exclude_none=True)
        )


class PersistedCreditTests(_CreditEngineTests):
    """The balance lands on the persisted event, which ``/events`` serves."""

    async def test_the_tool_call_row_carries_the_balance(self) -> None:
        engine = await self.make_engine(hosted=True)
        recorder = AsyncMock()

        with patch("app.engine.engine.store_match_activity", recorder):
            await engine.execute_tool_call(
                AgentType.PRISONER, ToolCall(name="bash", arguments={"command": "id"})
            )

        rows = [
            call.kwargs
            for call in recorder.await_args_list
            if call.kwargs.get("event_type") == "tool_call"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"]["credits"], 98)

    async def test_the_events_schema_surfaces_the_balance(self) -> None:
        """What ``GET /matches/events`` returns, from the persisted row."""
        row = SimpleNamespace(
            id=uuid4(),
            match_id=uuid4(),
            actor="prisoner",
            event_type="tool_call",
            action={"tool": "bash", "arguments": {"command": "id"}},
            result={"success": True, "exit_code": 0, "error": None, "credits": 98},
            timestamp=datetime.now(UTC),
        )

        event = MatchEventSchema.model_validate(row)

        self.assertEqual(event.result["credits"], 98)


if __name__ == "__main__":
    unittest.main()
