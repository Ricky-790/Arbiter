"""The Strategy Reviewer: its prompt, its read-only tools, and its stream.

Offline. The tools are thin wrappers over ``app.reviewer``, which owns the
queries and is exercised against a real PostgreSQL in development; what is
pinned here is what the reviewer is allowed to ask, that the match id is bound
rather than model-supplied, and what the endpoint streams.
"""

import asyncio
import base64
import json
import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import HTTPException

from app.agents.models import AgentType
from app.agents.strategy_reviewer import (
    ReviewRequest,
    StrategyReviewerAgent,
    build_review_prompt,
)
from app.agents.strategy_reviewer.prompt import tools_for
from app.agents.tools.review_tools import (
    REVIEW_TOOL_NAMES,
    ReviewContext,
    build_review_registry,
)
from app.api.routes import strategy_review as routes
from app.api.schemas.dto_models import ReviewStrategyRequest
from app.db.services import matches_service, strategies_service
from app.reviewer import service as reviewer
from app.reviewer.models import (
    ConversationEntry,
    MatchOverview,
    MatchStats,
    Page,
    SideStats,
)

MATCH_ID = uuid4()
CHALLENGE_ID = uuid4()


def _generate_keys() -> tuple[bytes, bytes]:
    """A throwaway pair, used the way the browser uses the published one."""
    from app.secrets.gen_rsa_keys import generate

    return generate(2048)


def _env_pair(public_pem: bytes, private_pem: bytes) -> dict[str, str]:
    return {
        "ARBITER_RSA_PUBLIC_KEY": base64.b64encode(public_pem).decode(),
        "ARBITER_RSA_PRIVATE_KEY": base64.b64encode(private_pem).decode(),
    }


def _encrypt(public_pem: bytes, plaintext: str) -> str:
    """What the browser sends in an api-key field."""
    key = serialization.load_pem_public_key(public_pem)
    ciphertext = key.encrypt(
        plaintext.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("ascii")


class _ReviewerStub:
    """An agent that never runs: these tests stop before the stream is read."""

    def __init__(self, **kwargs: object) -> None:
        pass

    async def run_turn(self) -> str:
        return "better strategy"


def page(items: list) -> Page:
    return Page(items=items, total=len(items), offset=0, limit=20, has_more=False)


def context() -> ReviewContext:
    return ReviewContext(match_id=MATCH_ID)


def get_tool(name: str):
    return build_review_registry().get(name)


class ReviewPromptTests(unittest.TestCase):
    def request(self, **overrides) -> ReviewRequest:
        values = {
            "side": "prisoner",
            "strategy": "Read the assemble script first.",
            "challenge_name": "The Hidden Artifact",
            "challenge_description": "Recover the artifact from the vault.",
            "win_condition": "prisoner_submits_flag",
            "hint": "The artifact is not one readable file.",
        }
        values.update(overrides)
        return ReviewRequest(**values)

    def test_the_prompt_carries_the_challenge_and_the_strategy(self) -> None:
        prompt = build_review_prompt(self.request())

        self.assertIn("The Hidden Artifact", prompt)
        self.assertIn("Recover the artifact from the vault.", prompt)
        self.assertIn("prisoner_submits_flag", prompt)
        self.assertIn("Read the assemble script first.", prompt)
        self.assertIn("The artifact is not one readable file.", prompt)

    def test_the_prompt_names_the_tools_that_side_actually_has(self) -> None:
        prompt = build_review_prompt(self.request())

        for tool in tools_for("prisoner"):
            self.assertIn(tool, prompt)

    def test_the_prompt_says_which_side_is_being_improved(self) -> None:
        prompt = build_review_prompt(self.request(side="warden"))

        self.assertIn("write a better strategy for the warden", prompt)
        self.assertNotIn("write a better strategy for the prisoner", prompt)

    def test_a_missing_strategy_is_stated_rather_than_left_blank(self) -> None:
        prompt = build_review_prompt(self.request(strategy="", hint=None))

        self.assertIn("(none was given)", prompt)

    def test_a_whitespace_hint_is_left_out(self) -> None:
        prompt = build_review_prompt(self.request(hint="   "))

        self.assertNotIn("is told up front", prompt)

    def test_the_prompt_only_carries_the_side_owning_hint(self) -> None:
        """The hints are what keeps the two roles' knowledge asymmetric, and the
        reviewer's answer is handed straight to that side."""
        prompt = build_review_prompt(
            self.request(side="prisoner", hint="PRISONER-ONLY")
        )

        self.assertIn("PRISONER-ONLY", prompt)
        self.assertNotIn("WARDEN-ONLY", prompt)


class ReviewToolSchemaTests(unittest.TestCase):
    def test_no_review_tool_accepts_a_match_id(self) -> None:
        """The match is bound before the run; the model cannot choose one."""
        from app.agents.base import _build_tool_definitions

        for definition in _build_tool_definitions(
            build_review_registry(), REVIEW_TOOL_NAMES
        ):
            properties = definition.parameters_json_schema["properties"]
            self.assertNotIn("match_id", properties, definition.name)

    def test_arguments_are_typed_rather_than_left_as_objects(self) -> None:
        """A module using deferred annotations must still produce real types."""
        from app.agents.base import _build_tool_definitions

        definitions = {
            d.name: d.parameters_json_schema["properties"]
            for d in _build_tool_definitions(
                build_review_registry(), REVIEW_TOOL_NAMES
            )
        }
        self.assertEqual(definitions["get_tool_calls"]["n"], {"type": "integer"})
        self.assertEqual(
            definitions["get_tool_calls"]["user"],
            {"type": "string", "nullable": True},
        )
        self.assertEqual(
            definitions["get_tool_calls"]["success_only"], {"type": "boolean"}
        )
        self.assertEqual(
            _build_tool_definitions(build_review_registry(), {"get_messages"})[
                0
            ].parameters_json_schema["required"],
            ["user"],
        )


class ReviewToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_bound_match_id_is_passed_through(self) -> None:
        calls = AsyncMock(return_value=page([]))
        with patch.object(reviewer, "get_tool_calls", calls):
            await get_tool("get_tool_calls").execute(context(), n=5)

        self.assertEqual(calls.await_args.args, (MATCH_ID, None))
        self.assertEqual(calls.await_args.kwargs["limit"], 5)

    async def test_n_maps_onto_the_reviewers_limit(self) -> None:
        calls = AsyncMock(return_value=page([]))
        with patch.object(reviewer, "get_conversation", calls):
            await get_tool("get_messages").execute(
                context(), user="warden", n=7, offset=14
            )

        self.assertEqual(calls.await_args.args, (MATCH_ID, "warden"))
        self.assertEqual(calls.await_args.kwargs, {"offset": 14, "limit": 7})

    async def test_a_page_comes_back_as_json_with_its_paging_fields(self) -> None:
        entry = ConversationEntry(index=0, kind="text", text="hello")
        result = None
        with patch.object(
            reviewer, "get_conversation", AsyncMock(return_value=page([entry]))
        ):
            result = await get_tool("get_messages").execute(context(), user="prisoner")

        self.assertTrue(result.success)
        payload = json.loads(result.output)
        self.assertEqual(payload["items"][0]["text"], "hello")
        self.assertEqual(
            set(payload), {"items", "total", "offset", "limit", "has_more"}
        )

    async def test_the_summary_and_stats_take_no_arguments(self) -> None:
        with (
            patch.object(
                reviewer,
                "get_match_overview",
                AsyncMock(
                    return_value=MatchOverview(
                        match_id=MATCH_ID,
                        status="completed",
                        winner="prisoner",
                        win_condition="w",
                        challenge_id=CHALLENGE_ID,
                        challenge_name="c",
                        prisoner_provider="openai",
                        prisoner_model="m",
                        warden_provider="openai",
                        warden_model="m",
                        parent_match_id=None,
                        branch_event_id=None,
                        duration_seconds=None,
                        started_at=None,
                        finished_at=None,
                        created_at=datetime.now(UTC),
                    )
                ),
            ),
            patch.object(
                reviewer,
                "get_match_stats",
                AsyncMock(
                    return_value=MatchStats(
                        match_id=MATCH_ID,
                        prisoner=SideStats(
                            actor="prisoner",
                            credits_remaining=1,
                            tool_calls=1,
                            successful_tool_calls=1,
                            failed_tool_calls=0,
                            rejected_tool_calls=0,
                        ),
                        warden=SideStats(
                            actor="warden",
                            credits_remaining=1,
                            tool_calls=1,
                            successful_tool_calls=1,
                            failed_tool_calls=0,
                            rejected_tool_calls=0,
                        ),
                    )
                ),
            ),
        ):
            summary = await get_tool("get_match_summary").execute(context())
            stats = await get_tool("get_match_stats").execute(context())

        self.assertTrue(summary.success)
        self.assertTrue(stats.success)

    async def test_a_bad_side_is_refused_without_a_query(self) -> None:
        calls = AsyncMock()
        with patch.object(reviewer, "get_tool_calls", calls):
            result = await get_tool("get_tool_calls").execute(context(), user="system")

        self.assertFalse(result.success)
        self.assertIn("prisoner, warden", result.error or "")
        calls.assert_not_awaited()

    async def test_bad_bounds_are_refused_without_a_query(self) -> None:
        calls = AsyncMock()
        with patch.object(reviewer, "get_trap_events", calls):
            zero = await get_tool("get_trap_events").execute(context(), n=0)
            negative = await get_tool("get_trap_events").execute(context(), offset=-1)

        self.assertFalse(zero.success)
        self.assertFalse(negative.success)
        calls.assert_not_awaited()

    async def test_an_unknown_event_type_is_refused(self) -> None:
        calls = AsyncMock()
        with patch.object(reviewer, "get_match_events", calls):
            result = await get_tool("get_match_events").execute(
                context(), event_type="not_a_type"
            )

        self.assertFalse(result.success)
        self.assertIn("not_a_type", result.error or "")
        calls.assert_not_awaited()

    async def test_a_missing_briefing_reads_as_a_failure_not_a_crash(self) -> None:
        with patch.object(reviewer, "get_agent_briefing", AsyncMock(return_value=None)):
            result = await get_tool("get_agent_briefing").execute(
                context(), user="prisoner"
            )

        self.assertFalse(result.success)

    async def test_a_review_tool_is_never_offered_inside_a_match(self) -> None:
        for actor in AgentType:
            self.assertEqual(
                build_review_registry().get_for_agent(actor), [], actor.value
            )

    async def test_an_oversized_page_is_sent_whole_with_a_notice(self) -> None:
        """Never truncated: a silently shortened match is worse than a large one."""
        from app.agents.tools.review_tools import base

        with patch.object(base, "lower_token_limit", return_value=1):
            result = base.json_result(page([ConversationEntry(index=0, kind="text")]))

        self.assertTrue(result.success)
        self.assertIsNotNone(result.notice)
        self.assertIn("smaller n", result.notice or "")


class ReviewStreamTests(unittest.IsolatedAsyncioTestCase):
    """The endpoint: validation before the stream, then the frames it emits."""

    def payload(self, **overrides) -> ReviewStrategyRequest:
        values = {
            "strategy_id": uuid4(),
            "match_id": MATCH_ID,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
        }
        values.update(overrides)
        return ReviewStrategyRequest(**values)

    def fake_session(self) -> object:
        row = SimpleNamespace(
            name="The Hidden Artifact",
            description="Recover it.",
            win_condition="prisoner_submits_flag",
            prisoner_hint="P-HINT",
            warden_hint="W-HINT",
        )
        return SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(first=lambda: row)
            )
        )

    def strategy(self, side: str = "prisoner", challenge_id: UUID = CHALLENGE_ID):
        return SimpleNamespace(
            strategy=SimpleNamespace(
                id=uuid4(),
                match_id=MATCH_ID,
                challenge_id=challenge_id,
                user=side,
                strategy="Read the assemble script first.",
            ),
            challenge_name="The Hidden Artifact",
        )

    def match(self, challenge_id: UUID = CHALLENGE_ID):
        return SimpleNamespace(id=MATCH_ID, challenge_id=challenge_id)

    async def collect(self, response) -> list[dict]:
        frames = []
        async for chunk in response.body_iterator:
            frames.append(json.loads(chunk.removeprefix("data: ").strip()))
        return frames

    async def test_the_stream_stays_alive_while_a_retry_is_waited_out(self) -> None:
        """A provider retry is 45s of silence, so the stream must not go quiet.

        A connection dropped for idling cancels the review, which would turn a
        recoverable 429 into a lost run. The gap is filled with SSE comments,
        which carry no ``data:`` line and so are not frames.
        """

        class SlowReviewer:
            def __init__(self, **kwargs):
                pass

            async def run_turn(self):
                await asyncio.sleep(0.05)
                return "Eventually better."

        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service, "get_strategy_row", AsyncMock(return_value=self.strategy())
            ),
            patch.object(matches_service, "get_match", AsyncMock(return_value=self.match())),
            patch.object(routes, "StrategyReviewerAgent", SlowReviewer),
            patch.object(routes, "REVIEW_KEEP_ALIVE_SECONDS", 0.005),
        ):
            response = await routes.review_strategy(
                self.payload(), session=self.fake_session()
            )
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertIn(": keep-alive\n\n", chunks)
        frames = [
            json.loads(chunk.removeprefix("data: ").strip())
            for chunk in chunks
            if chunk.startswith("data: ")
        ]
        self.assertEqual(frames[0]["type"], "review_started")
        self.assertEqual(frames[-1]["type"], "review_finished")
        self.assertEqual(frames[-1]["output"], "Eventually better.")

    async def test_the_stream_reports_progress_then_the_strategy(self) -> None:
        created: dict = {}

        class FakeReviewer:
            def __init__(self, **kwargs):
                created.update(kwargs)

            async def run_turn(self):
                sink = created["on_event"]
                await sink("review_tool_call", {"tool": "get_match_stats"})
                await sink("review_tool_result", {"tool": "get_match_stats"})
                return "  Do the better thing instead.  "

        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service, "get_strategy_row", AsyncMock(return_value=self.strategy())
            ),
            patch.object(matches_service, "get_match", AsyncMock(return_value=self.match())),
            patch.object(routes, "StrategyReviewerAgent", FakeReviewer),
        ):
            response = await routes.review_strategy(
                self.payload(), session=self.fake_session()
            )
            frames = await self.collect(response)

        self.assertEqual(frames[0]["type"], "review_started")
        self.assertIn("review_tool_call", [f["type"] for f in frames])
        final = frames[-1]
        self.assertEqual(final["type"], "review_finished")
        self.assertEqual(final["output"], "  Do the better thing instead.  ")

    async def test_the_review_reaches_the_agent_with_the_bound_match(self) -> None:
        created: dict = {}

        class FakeReviewer:
            def __init__(self, **kwargs):
                created.update(kwargs)

            async def run_turn(self):
                return "strategy"

        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service, "get_strategy_row", AsyncMock(return_value=self.strategy())
            ),
            patch.object(matches_service, "get_match", AsyncMock(return_value=self.match())),
            patch.object(routes, "StrategyReviewerAgent", FakeReviewer),
        ):
            await self.collect(
                await routes.review_strategy(
                    self.payload(), session=self.fake_session()
                )
            )

        self.assertEqual(created["context"].match_id, MATCH_ID)
        self.assertEqual(created["request"].side, "prisoner")
        self.assertEqual(created["request"].hint, "P-HINT")
        self.assertEqual(created["model_name"], "openai:gpt-4o-mini")

    async def test_nothing_is_saved(self) -> None:
        """The endpoint returns a proposal; promoting it is a separate call."""

        class FakeReviewer:
            def __init__(self, **kwargs):
                pass

            async def run_turn(self):
                return "strategy"

        create = AsyncMock()
        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service, "get_strategy_row", AsyncMock(return_value=self.strategy())
            ),
            patch.object(strategies_service, "create_for_match", create),
            patch.object(matches_service, "get_match", AsyncMock(return_value=self.match())),
            patch.object(routes, "StrategyReviewerAgent", FakeReviewer),
        ):
            await self.collect(
                await routes.review_strategy(
                    self.payload(), session=self.fake_session()
                )
            )

        create.assert_not_awaited()

    async def test_a_review_that_produces_nothing_is_an_error_frame(self) -> None:
        class FakeReviewer:
            def __init__(self, **kwargs):
                pass

            async def run_turn(self):
                return None

        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service, "get_strategy_row", AsyncMock(return_value=self.strategy())
            ),
            patch.object(matches_service, "get_match", AsyncMock(return_value=self.match())),
            patch.object(routes, "StrategyReviewerAgent", FakeReviewer),
        ):
            frames = await self.collect(
                await routes.review_strategy(
                    self.payload(), session=self.fake_session()
                )
            )

        self.assertEqual(frames[-1]["type"], "review_error")

    async def test_a_crashing_review_becomes_an_error_frame(self) -> None:
        class FakeReviewer:
            def __init__(self, **kwargs):
                pass

            async def run_turn(self):
                raise RuntimeError("provider exploded")

        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service, "get_strategy_row", AsyncMock(return_value=self.strategy())
            ),
            patch.object(matches_service, "get_match", AsyncMock(return_value=self.match())),
            patch.object(routes, "StrategyReviewerAgent", FakeReviewer),
        ):
            frames = await self.collect(
                await routes.review_strategy(
                    self.payload(), session=self.fake_session()
                )
            )

        self.assertEqual(frames[-1]["type"], "review_error")
        self.assertIn("provider exploded", frames[-1]["detail"])

    async def test_an_unknown_strategy_is_not_found(self) -> None:
        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service, "get_strategy_row", AsyncMock(return_value=None)
            ),self.assertRaises(HTTPException) as raised
        ):
            await routes.review_strategy(
                self.payload(), session=self.fake_session()
            )

        self.assertEqual(raised.exception.status_code, 404)

    async def test_an_unknown_match_is_not_found(self) -> None:
        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service, "get_strategy_row", AsyncMock(return_value=self.strategy())
            ),
            patch.object(matches_service, "get_match", AsyncMock(return_value=None)),
            self.assertRaises(HTTPException) as raised,
        ):
            await routes.review_strategy(self.payload(), session=self.fake_session())

        self.assertEqual(raised.exception.status_code, 404)

    async def test_a_strategy_from_another_challenge_is_rejected(self) -> None:
        with (
            patch.object(routes, "check_model_exists", AsyncMock()),
            patch.object(
                strategies_service,
                "get_strategy_row",
                AsyncMock(return_value=self.strategy(challenge_id=uuid4())),
            ),
            patch.object(matches_service, "get_match", AsyncMock(return_value=self.match())),
            self.assertRaises(HTTPException) as raised,
        ):
            await routes.review_strategy(self.payload(), session=self.fake_session())

        self.assertEqual(raised.exception.status_code, 400)

    async def test_an_unknown_provider_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await routes.review_strategy(
                self.payload(provider="nope"), session=self.fake_session()
            )

        self.assertEqual(raised.exception.status_code, 400)

    async def test_a_missing_key_is_rejected(self) -> None:
        check = AsyncMock()
        with (
            patch.object(routes, "check_model_exists", check),
            self.assertRaises(HTTPException) as raised,
        ):
            await routes.review_strategy(
                self.payload(api_key=None), session=self.fake_session()
            )

        self.assertEqual(raised.exception.status_code, 400)
        check.assert_not_awaited()

    async def test_an_unusable_model_is_rejected_before_streaming(self) -> None:
        from app.agents.agents_directory import ModelCheckError

        with patch.object(
            routes,
            "check_model_exists",
            AsyncMock(side_effect=ModelCheckError("not_found", "no such model")),
        ), self.assertRaises(HTTPException) as raised:
            await routes.review_strategy(
                self.payload(), session=self.fake_session()
            )

        self.assertEqual(raised.exception.status_code, 400)

    async def test_a_browser_encrypted_key_is_decrypted_before_use(self) -> None:
        """The reviewer's key is one of the api-key fields the transport covers.

        Without this the ciphertext would go to the provider as the credential
        and the review would fail with a rejection that explains nothing.
        """
        public_pem, private_pem = _generate_keys()
        check = AsyncMock()
        with (
            patch.dict(os.environ, _env_pair(public_pem, private_pem)),
            patch.object(routes, "check_model_exists", check),
            patch.object(
                strategies_service,
                "get_strategy_row",
                AsyncMock(return_value=self.strategy()),
            ),
            patch.object(
                matches_service, "get_match", AsyncMock(return_value=self.match())
            ),
            patch.object(routes, "StrategyReviewerAgent", _ReviewerStub),
        ):
            await routes.review_strategy(
                self.payload(api_key=_encrypt(public_pem, "sk-encrypted")),
                session=self.fake_session(),
            )

        check.assert_awaited_once_with("openai", "gpt-4o-mini", "sk-encrypted")

    async def test_a_key_that_cannot_be_decrypted_is_rejected(self) -> None:
        """Two independent pairs: the server holds one, the browser used the other."""
        public_pem, private_pem = _generate_keys()
        other_public, _other_private = _generate_keys()
        check = AsyncMock()
        with (
            patch.dict(os.environ, _env_pair(public_pem, private_pem)),
            patch.object(routes, "check_model_exists", check),
            self.assertRaises(HTTPException) as raised,
        ):
            await routes.review_strategy(
                self.payload(api_key=_encrypt(other_public, "sk-stale")),
                session=self.fake_session(),
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("api_key", raised.exception.detail)
        # Refused before anything reached the provider.
        check.assert_not_awaited()


class ReviewerAgentWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_agent_runs_the_review_prompt_not_a_match_objective(self) -> None:
        agent = StrategyReviewerAgent(
            model_name="openai:gpt-4o-mini",
            request=ReviewRequest(
                side="warden",
                strategy="Watch the vault.",
                challenge_name="The Hidden Artifact",
                challenge_description="Recover it.",
                win_condition="w",
            ),
            context=context(),
            api_key="sk-test",
        )

        prompt = agent._turn_prompt("ignored scratchpad")

        self.assertIn("Watch the vault.", prompt)
        self.assertNotIn("Your scratchpad:", prompt)

    async def test_a_runaway_review_is_bounded(self) -> None:
        self.assertIsNotNone(StrategyReviewerAgent._request_limit)


if __name__ == "__main__":
    unittest.main()
