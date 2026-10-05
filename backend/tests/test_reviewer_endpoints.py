"""Review endpoints: the composed summary, the listings, and their HTTP contract.

Offline. The reviewer's queries are exercised against a real PostgreSQL in
development; what is pinned here is what the routes do with their answers --
which side a summary is scoped to, what a missing match becomes, and that the
paging bounds are the reviewer's own.
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.app import app
from app.reviewer import service as reviewer
from app.reviewer.models import (
    AgentBriefing,
    ConversationEntry,
    MatchEventRecord,
    MatchOverview,
    MatchStats,
    Page,
    SideStats,
    ThoughtRecord,
    ToolCallRecord,
    TrapEvent,
)
from app.reviewer.service import MAX_LIMIT

MATCH_ID = uuid4()
CHALLENGE_ID = uuid4()
#: The library row the prisoner's strategy was promoted to, if it was.
PROMOTED_ID = uuid4()
NOW = datetime.now(timezone.utc)
BASE = "/api/v1/reviewer"


def overview(**overrides: object) -> MatchOverview:
    values: dict[str, object] = {
        "match_id": MATCH_ID,
        "status": "completed",
        "winner": "prisoner",
        "win_condition": "prisoner_submits_flag",
        "challenge_id": CHALLENGE_ID,
        "challenge_name": "The Hidden Artifact",
        "challenge_description": "Recover the artifact from the vault.",
        "prisoner_provider": "openai",
        "prisoner_model": "gpt-4o",
        "warden_provider": "anthropic",
        "warden_model": "claude-sonnet-4.6",
        "strategy": {
            "prisoner": "Read the assemble script first.",
            "warden": "Watch the vault directory.",
        },
        "strategy_id": {"prisoner": str(PROMOTED_ID)},
        "parent_match_id": None,
        "branch_event_id": None,
        "duration_seconds": 42.5,
        "started_at": NOW,
        "finished_at": NOW,
        "created_at": NOW,
    }
    values.update(overrides)
    return MatchOverview(**values)


def side(actor: str, **overrides: object) -> SideStats:
    values: dict[str, object] = {
        "actor": actor,
        "credits_remaining": 71,
        "tool_calls": 9,
        "tool_calls_by_name": {"read_file": 4, "write_file": 5},
        "successful_tool_calls": 7,
        "failed_tool_calls": 1,
        "rejected_tool_calls": 1,
    }
    values.update(overrides)
    return SideStats(**values)


def stats(**overrides: object) -> MatchStats:
    values: dict[str, object] = {
        "match_id": MATCH_ID,
        "prisoner": side("prisoner", times_trapped=2),
        "warden": side("warden", traps_armed=3, traps_triggered=2),
        "triggered_trap_tools": {"watch_file": 2},
    }
    values.update(overrides)
    return MatchStats(**values)


def page(items: list[object], total: int, offset: int, limit: int) -> Page:
    return Page(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )


async def briefing_for(match_id: object, actor: str) -> AgentBriefing:
    """The reviewer answers per side, so the fake has to as well."""
    return AgentBriefing(actor=actor, strategy="parsed from the prompt", briefing="full")


class MatchSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def _get(self, user: str | None = None) -> list[dict]:
        """The summary always answers with a list, one entry per side asked for."""
        params: dict[str, object] = {"match_id": MATCH_ID}
        if user is not None:
            params["user"] = user
        with (
            patch.object(
                reviewer, "get_match_overview", AsyncMock(return_value=overview())
            ),
            patch.object(reviewer, "get_match_stats", AsyncMock(return_value=stats())),
            patch.object(
                reviewer, "get_agent_briefing", AsyncMock(side_effect=briefing_for)
            ),
        ):
            response = self.client.get(f"{BASE}/summary", params=params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_a_named_side_returns_exactly_one_summary(self) -> None:
        for user in ("prisoner", "warden"):
            body = self._get(user)
            self.assertEqual(len(body), 1, user)
            self.assertEqual(body[0]["user"], user)

    def test_omitting_the_side_returns_both_prisoner_first(self) -> None:
        body = self._get()

        self.assertEqual([entry["user"] for entry in body], ["prisoner", "warden"])

    def test_an_entry_carries_only_its_own_side(self) -> None:
        """There is no opponent block: both sides come from the list instead."""
        prisoner, warden = self._get()

        for entry in (prisoner, warden):
            self.assertNotIn("opponent_stats", entry)
        self.assertEqual(prisoner["stats"]["actor"], "prisoner")
        self.assertEqual(warden["stats"]["actor"], "warden")
        # The trap counters each side owns are on that side's entry only.
        self.assertEqual(prisoner["stats"]["traps_armed"], None)
        self.assertEqual(warden["stats"]["times_trapped"], None)

    def test_each_entry_in_the_both_view_carries_its_own_strategy(self) -> None:
        prisoner, warden = self._get()

        self.assertEqual(prisoner["strategy"], "Read the assemble script first.")
        self.assertEqual(warden["strategy"], "Watch the vault directory.")
        # The match block is shared, so both entries can see the whole picture.
        self.assertEqual(prisoner["match"], warden["match"])

    def test_each_entry_in_the_both_view_carries_its_own_briefing(self) -> None:
        prisoner, warden = self._get()

        self.assertEqual(prisoner["briefing"]["actor"], "prisoner")
        self.assertEqual(warden["briefing"]["actor"], "warden")

    def test_the_summary_is_scoped_to_the_requested_side(self) -> None:
        body = self._get("warden")

        self.assertEqual(body[0]["user"], "warden")
        self.assertEqual(body[0]["stats"]["actor"], "warden")
        self.assertNotIn("opponent_stats", body[0])

    def test_the_prisoner_view_takes_the_prisoner_stats(self) -> None:
        (entry,) = self._get("prisoner")

        self.assertEqual(entry["stats"]["times_trapped"], 2)
        # The Warden's counters are absent rather than copied across.
        self.assertEqual(entry["stats"]["traps_triggered"], None)
        self.assertEqual(entry["stats"]["traps_armed"], None)

    def test_the_warden_view_takes_the_warden_stats(self) -> None:
        (entry,) = self._get("warden")

        self.assertEqual(entry["stats"]["traps_armed"], 3)
        self.assertEqual(entry["stats"]["times_trapped"], None)

    def test_the_strategy_comes_from_the_match_row_not_the_prompt(self) -> None:
        """The column is authoritative; the parsed briefing is only narration."""
        (entry,) = self._get("prisoner")

        self.assertEqual(entry["strategy"], "Read the assemble script first.")
        self.assertEqual(entry["briefing"]["strategy"], "parsed from the prompt")

    def test_the_other_sides_strategy_is_still_carried(self) -> None:
        (entry,) = self._get("prisoner")

        self.assertEqual(
            entry["match"]["strategy"]["warden"], "Watch the vault directory."
        )
        self.assertEqual(entry["match"]["strategy_id"]["prisoner"], str(PROMOTED_ID))

    def test_the_challenge_details_are_included(self) -> None:
        (entry,) = self._get("prisoner")

        self.assertEqual(entry["match"]["challenge_name"], "The Hidden Artifact")
        self.assertEqual(
            entry["match"]["challenge_description"],
            "Recover the artifact from the vault.",
        )
        self.assertEqual(entry["match"]["win_condition"], "prisoner_submits_flag")

    def test_the_trap_tool_breakdown_is_shared(self) -> None:
        for user in ("prisoner", "warden"):
            (entry,) = self._get(user)
            self.assertEqual(entry["triggered_trap_tools"], {"watch_file": 2})

    def test_a_side_without_a_strategy_reads_as_null(self) -> None:
        with (
            patch.object(
                reviewer,
                "get_match_overview",
                AsyncMock(return_value=overview(strategy={})),
            ),
            patch.object(reviewer, "get_match_stats", AsyncMock(return_value=stats())),
            patch.object(reviewer, "get_agent_briefing", AsyncMock(return_value=None)),
        ):
            body = self.client.get(
                f"{BASE}/summary", params={"match_id": MATCH_ID, "user": "warden"}
            ).json()

        (entry,) = body
        self.assertIsNone(entry["strategy"])
        self.assertIsNone(entry["briefing"])

    def test_an_unknown_match_is_not_found(self) -> None:
        with patch.object(reviewer, "get_match_overview", AsyncMock(return_value=None)):
            response = self.client.get(
                f"{BASE}/summary", params={"match_id": uuid4(), "user": "prisoner"}
            )

        self.assertEqual(response.status_code, 404)

    def test_a_match_that_vanishes_between_reads_is_not_found(self) -> None:
        with (
            patch.object(
                reviewer, "get_match_overview", AsyncMock(return_value=overview())
            ),
            patch.object(reviewer, "get_match_stats", AsyncMock(return_value=None)),
        ):
            response = self.client.get(
                f"{BASE}/summary", params={"match_id": MATCH_ID, "user": "prisoner"}
            )

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_side_is_rejected(self) -> None:
        response = self.client.get(
            f"{BASE}/summary", params={"match_id": MATCH_ID, "user": "system"}
        )

        self.assertEqual(response.status_code, 422)


class ReviewListingTests(unittest.TestCase):
    """The paginated detail endpoints: pass-through, bounds and 404s."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _exists(self) -> object:
        return patch.object(reviewer, "match_exists", AsyncMock(return_value=True))

    def test_the_conversation_page_is_passed_through(self) -> None:
        entries = [
            ConversationEntry(index=0, kind="user-prompt", actor="prisoner", text="hi"),
            ConversationEntry(index=1, kind="text", text="thinking"),
        ]
        fake = AsyncMock(return_value=page(entries, total=9, offset=2, limit=2))
        with self._exists(), patch.object(reviewer, "get_conversation", fake):
            body = self.client.get(
                f"{BASE}/conversation",
                params={
                    "match_id": MATCH_ID,
                    "user": "prisoner",
                    "offset": 2,
                    "limit": 2,
                },
            ).json()

        self.assertEqual(fake.await_args.kwargs, {"offset": 2, "limit": 2})
        self.assertEqual(fake.await_args.args, (MATCH_ID, "prisoner"))
        self.assertEqual(body["total"], 9)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["items"][0]["index"], 0)
        self.assertEqual(body["items"][0]["kind"], "user-prompt")

    def test_the_conversation_is_scoped_to_one_side(self) -> None:
        fake = AsyncMock(return_value=page([], total=0, offset=0, limit=20))
        with self._exists(), patch.object(reviewer, "get_conversation", fake):
            self.client.get(
                f"{BASE}/conversation",
                params={"match_id": MATCH_ID, "user": "warden"},
            )

        self.assertEqual(fake.await_args.args, (MATCH_ID, "warden"))

    def test_tool_call_filters_reach_the_reviewer(self) -> None:
        fake = AsyncMock(
            return_value=page(
                [
                    ToolCallRecord(
                        event_id=uuid4(),
                        timestamp=NOW,
                        actor="prisoner",
                        tool="read_file",
                        arguments={"path": "/vault/a"},
                        success=True,
                        exit_code=0,
                        error=None,
                        failure_category=None,
                    )
                ],
                total=1,
                offset=0,
                limit=20,
            )
        )
        with self._exists(), patch.object(reviewer, "get_tool_calls", fake):
            body = self.client.get(
                f"{BASE}/tool-calls",
                params={
                    "match_id": MATCH_ID,
                    "user": "warden",
                    "success_only": "true",
                },
            ).json()

        self.assertEqual(fake.await_args.args, (MATCH_ID, "warden"))
        self.assertTrue(fake.await_args.kwargs["success_only"])
        self.assertEqual(body["items"][0]["tool"], "read_file")
        self.assertEqual(body["items"][0]["arguments"], {"path": "/vault/a"})
        self.assertTrue(body["items"][0]["success"])

    def test_success_only_defaults_to_off(self) -> None:
        fake = AsyncMock(return_value=page([], total=0, offset=0, limit=20))
        with self._exists(), patch.object(reviewer, "get_tool_calls", fake):
            self.client.get(
                f"{BASE}/tool-calls",
                params={"match_id": MATCH_ID, "user": "warden"},
            )

        self.assertFalse(fake.await_args.kwargs["success_only"])

    def test_thoughts_are_scoped_to_one_side(self) -> None:
        fake = AsyncMock(
            return_value=page(
                [ThoughtRecord(event_id=uuid4(), timestamp=NOW, actor="warden", content="hi")],
                total=1,
                offset=0,
                limit=20,
            )
        )
        with self._exists(), patch.object(reviewer, "get_agent_thoughts", fake):
            body = self.client.get(
                f"{BASE}/thoughts", params={"match_id": MATCH_ID, "user": "warden"}
            ).json()

        self.assertEqual(fake.await_args.args, (MATCH_ID, "warden"))
        self.assertEqual(body["items"][0]["content"], "hi")

    def test_traps_are_not_scoped_to_a_side(self) -> None:
        """A firing involves both sides, so there is no side to filter on."""
        fake = AsyncMock(
            return_value=page(
                [
                    TrapEvent(
                        event_id=uuid4(),
                        timestamp=NOW,
                        trap="watch_file",
                        target="/vault",
                        prisoner_turn=3,
                        warden_turn=2,
                    )
                ],
                total=1,
                offset=0,
                limit=20,
            )
        )
        with self._exists(), patch.object(reviewer, "get_trap_events", fake):
            body = self.client.get(
                f"{BASE}/traps", params={"match_id": MATCH_ID}
            ).json()

        self.assertEqual(fake.await_args.args, (MATCH_ID,))
        self.assertEqual(body["items"][0]["trap"], "watch_file")
        self.assertEqual(body["items"][0]["target"], "/vault")

    def test_events_pass_their_filters_through(self) -> None:
        fake = AsyncMock(
            return_value=page(
                [
                    MatchEventRecord(
                        event_id=uuid4(),
                        timestamp=NOW,
                        actor="system",
                        event_type="match_finished",
                        action={},
                        result=None,
                    )
                ],
                total=1,
                offset=0,
                limit=20,
            )
        )
        with self._exists(), patch.object(reviewer, "get_match_events", fake):
            self.client.get(
                f"{BASE}/events",
                params={
                    "match_id": MATCH_ID,
                    "event_type": "match_finished",
                    "user": "prisoner",
                },
            )

        self.assertEqual(
            fake.await_args.kwargs,
            {"event_type": "match_finished", "actor": "prisoner", "offset": 0, "limit": 20},
        )

    def test_an_unknown_event_type_is_rejected(self) -> None:
        response = self.client.get(
            f"{BASE}/events",
            params={"match_id": MATCH_ID, "event_type": "not_a_type"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not_a_type", response.json()["detail"])

    def test_an_unknown_match_is_not_found_on_every_listing(self) -> None:
        with patch.object(reviewer, "match_exists", AsyncMock(return_value=False)):
            for path, params in (
                (f"{BASE}/conversation", {"user": "prisoner"}),
                (f"{BASE}/tool-calls", {"user": "prisoner"}),
                (f"{BASE}/thoughts", {"user": "prisoner"}),
                (f"{BASE}/traps", {}),
                (f"{BASE}/events", {}),
            ):
                response = self.client.get(
                    path, params={"match_id": uuid4(), **params}
                )
                self.assertEqual(response.status_code, 404, path)

    def test_the_listings_do_not_run_without_a_match(self) -> None:
        """The existence check comes first, so a listing never runs for a ghost."""
        conversation = AsyncMock()
        with (
            patch.object(reviewer, "match_exists", AsyncMock(return_value=False)),
            patch.object(reviewer, "get_conversation", conversation),
        ):
            self.client.get(
                f"{BASE}/conversation",
                params={"match_id": uuid4(), "user": "prisoner"},
            )

        conversation.assert_not_awaited()


class PagingBoundsTests(unittest.TestCase):
    """The limit ceiling is the reviewer's, not a second number that can drift."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_a_limit_above_the_ceiling_is_rejected(self) -> None:
        response = self.client.get(
            f"{BASE}/conversation",
            params={"match_id": MATCH_ID, "user": "prisoner", "limit": MAX_LIMIT + 1},
        )

        self.assertEqual(response.status_code, 422)

    def test_the_ceiling_itself_is_allowed(self) -> None:
        fake = AsyncMock(return_value=page([], total=0, offset=0, limit=MAX_LIMIT))
        with (
            patch.object(reviewer, "match_exists", AsyncMock(return_value=True)),
            patch.object(reviewer, "get_conversation", fake),
        ):
            response = self.client.get(
                f"{BASE}/conversation",
                params={
                    "match_id": MATCH_ID,
                    "user": "prisoner",
                    "limit": MAX_LIMIT,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake.await_args.kwargs["limit"], MAX_LIMIT)

    def test_a_negative_offset_is_rejected(self) -> None:
        response = self.client.get(
            f"{BASE}/traps",
            params={"match_id": MATCH_ID, "offset": -1},
        )

        self.assertEqual(response.status_code, 422)

    def test_a_zero_limit_is_rejected(self) -> None:
        response = self.client.get(
            f"{BASE}/traps", params={"match_id": MATCH_ID, "limit": 0}
        )

        self.assertEqual(response.status_code, 422)

    def test_the_default_page_is_the_reviewers_default(self) -> None:
        fake = AsyncMock(return_value=page([], total=0, offset=0, limit=20))
        with (
            patch.object(reviewer, "match_exists", AsyncMock(return_value=True)),
            patch.object(reviewer, "get_trap_events", fake),
        ):
            self.client.get(f"{BASE}/traps", params={"match_id": MATCH_ID})

        self.assertEqual(fake.await_args.kwargs["limit"], reviewer.DEFAULT_LIMIT)
        self.assertEqual(fake.await_args.kwargs["offset"], 0)

    def test_tool_calls_are_paged_too(self) -> None:
        """Every listing that can grow takes a limit, not just the longest one."""
        fake = AsyncMock(return_value=page([], total=0, offset=0, limit=20))
        with (
            patch.object(reviewer, "match_exists", AsyncMock(return_value=True)),
            patch.object(reviewer, "get_tool_calls", fake),
        ):
            body = self.client.get(
                f"{BASE}/tool-calls",
                params={"match_id": MATCH_ID, "user": "prisoner"},
            ).json()

        self.assertEqual(
            set(body), {"items", "total", "offset", "limit", "has_more"}
        )


if __name__ == "__main__":
    unittest.main()
