"""Provider-level retry behaviour for one agent turn.

These pin the timing contract the Engine depends on: a turn retries retryable
provider errors a bounded number of times and then gives up *immediately*, so
the Engine can stop the match without waiting out a retry that will never
happen.
"""

import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic_ai.exceptions import ModelHTTPError

from app.agents.base import AgentUnavailableError, ToolChoosingAgent
from app.agents.strategy_reviewer import ReviewRequest, StrategyReviewerAgent
from app.agents.tools.review_tools import ReviewContext


def http_error(status: int, **headers: str) -> ModelHTTPError:
    return ModelHTTPError(
        status_code=status,
        model_name="test-model",
        body="provider refused",
        headers=headers or None,
    )


class FakeRunResult:
    def __init__(self, output: object) -> None:
        self.output = output

    def all_messages(self) -> list[str]:
        return [f"turn-{self.output}"]


class ScriptedModel:
    """Stands in for the Pydantic AI ``Agent``: one outcome per call."""

    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def run(
        self, prompt: str, message_history: object = None, **kwargs: object
    ) -> FakeRunResult:
        # ``**kwargs`` absorbs the usage limits a bounded agent passes.
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeRunResult(outcome)


def make_agent(model: object) -> ToolChoosingAgent:
    agent = ToolChoosingAgent(
        model_name="openai:gpt-4o-mini",
        api_key="test-key",
        instructions="test",
        allowed_tools={"bash"},
        scripted_calls=None,
    )
    agent._agent = model  # type: ignore[assignment]
    return agent


def make_reviewer(model: object) -> StrategyReviewerAgent:
    """The reviewer is the agent whose retry cooldown differs from a match's."""
    agent = StrategyReviewerAgent(
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
    agent._agent = model  # type: ignore[assignment]
    return agent


class RecordingSleep:
    """Records requested sleeps instead of waiting them out."""

    def __init__(self) -> None:
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


def collector(sink: list[tuple[str, dict[str, object]]]):
    async def reporter(event_type: str, attributes: dict[str, object]) -> None:
        sink.append((event_type, attributes))

    return reporter


class ProviderRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_rate_limits_give_up_without_a_final_sleep(self) -> None:
        """The last failure has nothing left to wait for.

        Sleeping there only delays the Engine terminating the match.
        """
        sleep = RecordingSleep()
        model = ScriptedModel(*[http_error(429) for _ in range(3)])
        agent = make_agent(model)
        reported: list[tuple[str, dict[str, object]]] = []
        agent.bind_event_reporter(collector(reported))

        with patch("app.agents.base.asyncio.sleep", sleep):
            with self.assertRaises(AgentUnavailableError) as raised:
                await agent.run_turn()

        self.assertEqual(model.calls, 3)
        self.assertEqual(sleep.seconds, [30.0, 30.0])
        self.assertIn("3 attempts", str(raised.exception))
        self.assertIn("429", str(raised.exception))
        # Only the attempts that actually retry are reported as retries.
        self.assertEqual(
            [event for event, _ in reported], ["agent_retry", "agent_retry"]
        )
        self.assertEqual([attrs["attempt"] for _, attrs in reported], [1, 2])
        self.assertEqual([attrs["max_attempts"] for _, attrs in reported], [3, 3])

    async def test_retry_after_is_honoured_capped_and_fallen_back_from(self) -> None:
        cases = [
            ({"retry-after": "7"}, 7.0),
            ({"retry-after": "9999"}, 60.0),
            # An HTTP-date is not a delay we can honour; fall back.
            ({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, 30.0),
            ({}, 30.0),
        ]

        for headers, expected in cases:
            with self.subTest(headers=headers):
                sleep = RecordingSleep()
                model = ScriptedModel(http_error(429, **headers), "recovered")
                agent = make_agent(model)

                with patch("app.agents.base.asyncio.sleep", sleep):
                    output = await agent.run_turn()

                self.assertEqual(output, "recovered")
                self.assertEqual(model.calls, 2)
                self.assertEqual(sleep.seconds, [expected])

    async def test_gateway_errors_are_retried_with_the_default_wait(self) -> None:
        for status in (503, 504):
            with self.subTest(status=status):
                sleep = RecordingSleep()
                # A Retry-After on a gateway error is not a rate limit.
                model = ScriptedModel(http_error(status, **{"retry-after": "5"}), "ok")
                agent = make_agent(model)

                with patch("app.agents.base.asyncio.sleep", sleep):
                    output = await agent.run_turn()

                self.assertEqual(output, "ok")
                self.assertEqual(sleep.seconds, [30.0])

    async def test_a_successful_retry_clears_the_failure_streak(self) -> None:
        sleep = RecordingSleep()
        model = ScriptedModel(http_error(429), "fine")
        agent = make_agent(model)

        with patch("app.agents.base.asyncio.sleep", sleep):
            output = await agent.run_turn()

        self.assertEqual(output, "fine")
        self.assertEqual(agent._consecutive_failures, 0)

    async def test_non_retryable_status_returns_none_then_declares_unavailable(
        self,
    ) -> None:
        model = ScriptedModel(*[http_error(400) for _ in range(3)])
        agent = make_agent(model)

        first = await agent.run_turn()
        second = await agent.run_turn()
        with self.assertRaises(AgentUnavailableError) as raised:
            await agent.run_turn()

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(model.calls, 3)
        self.assertIn("3 consecutive failed turns", str(raised.exception))


class StrategyReviewerRetryTests(unittest.IsolatedAsyncioTestCase):
    """The reviewer waits longer than a match agent, and on one fixed number.

    A match agent's 30s cooldown is spent against a match wall clock. A review
    has no such clock -- its caller is watching a stream -- so it rides a
    provider hiccup out for 45s instead of failing the whole run.
    """

    async def test_a_rate_limit_is_retried_after_45_seconds(self) -> None:
        sleep = RecordingSleep()
        model = ScriptedModel(http_error(429), "recovered")
        agent = make_reviewer(model)

        with patch("app.agents.base.asyncio.sleep", sleep):
            output = await agent.run_turn()

        self.assertEqual(output, "recovered")
        self.assertEqual(model.calls, 2)
        self.assertEqual(sleep.seconds, [45.0])

    async def test_gateway_errors_wait_the_same_45_seconds(self) -> None:
        for status in (503, 504):
            with self.subTest(status=status):
                sleep = RecordingSleep()
                model = ScriptedModel(http_error(status), "ok")
                agent = make_reviewer(model)

                with patch("app.agents.base.asyncio.sleep", sleep):
                    output = await agent.run_turn()

                self.assertEqual(output, "ok")
                self.assertEqual(sleep.seconds, [45.0])

    async def test_a_short_retry_after_does_not_shorten_the_cooldown(self) -> None:
        """Retrying sooner than the fixed cooldown only re-hits the limit.

        Distinct from a match agent, which does honour a short ``Retry-After``.
        """
        sleep = RecordingSleep()
        model = ScriptedModel(http_error(429, **{"retry-after": "3"}), "ok")
        agent = make_reviewer(model)

        with patch("app.agents.base.asyncio.sleep", sleep):
            output = await agent.run_turn()

        self.assertEqual(output, "ok")
        self.assertEqual(sleep.seconds, [45.0])

    async def test_a_long_retry_after_is_not_waited_out_past_the_cooldown(
        self,
    ) -> None:
        sleep = RecordingSleep()
        model = ScriptedModel(http_error(429, **{"retry-after": "9999"}), "ok")
        agent = make_reviewer(model)

        with patch("app.agents.base.asyncio.sleep", sleep):
            output = await agent.run_turn()

        self.assertEqual(output, "ok")
        self.assertEqual(sleep.seconds, [45.0])

    async def test_three_failures_give_up_without_a_final_sleep(self) -> None:
        sleep = RecordingSleep()
        model = ScriptedModel(*[http_error(503) for _ in range(3)])
        agent = make_reviewer(model)

        with (
            patch("app.agents.base.asyncio.sleep", sleep),
            self.assertRaises(AgentUnavailableError),
        ):
            await agent.run_turn()

        self.assertEqual(model.calls, 3)
        self.assertEqual(sleep.seconds, [45.0, 45.0])

    async def test_the_retry_is_reported_to_the_stream_sink(self) -> None:
        """The caller is watching a stream, so a 45s wait must be visible there."""
        sleep = RecordingSleep()
        model = ScriptedModel(http_error(429), "ok")
        agent = make_reviewer(model)
        reported: list[tuple[str, dict[str, object]]] = []
        agent.bind_event_reporter(collector(reported))

        with patch("app.agents.base.asyncio.sleep", sleep):
            await agent.run_turn()

        self.assertEqual([event for event, _ in reported], ["agent_retry"])
        self.assertEqual(reported[0][1]["wait_seconds"], 45.0)
        self.assertEqual(reported[0][1]["reason"], "rate_limit")
