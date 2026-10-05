"""Strategies: label derivation, the promotion route, and strategy resolution.

Offline. The queries themselves are exercised against a real PostgreSQL in
development; what is pinned here is the decision logic -- which text a side is
started with, and what promotion does when it is asked twice.
"""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.app import app
from app.api.routes.matches import _resolve_strategies
from app.api.routes.strategy_review import save_strategy
from app.api.schemas.dto_models import SaveStrategyRequest
from app.db.models import Match
from app.db.services import matches_service, strategies_service
from app.db.services.strategy_service import (
    MAX_ONE_LINE_LENGTH,
    StrategyRow,
    one_line_description,
)
from app.reviewer.service import DEFAULT_LIMIT


class FakeSession:
    """Only what the promotion route reads before it calls the services."""

    def __init__(self, match: object) -> None:
        self._match = match

    async def get(self, model: object, key: object) -> object:
        return self._match if model is Match else None


def match(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "challenge_id": uuid4(),
        "challenge": SimpleNamespace(name="The Hidden Artifact"),
        "strategy": {"prisoner": "Look at the assemble script."},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def stored_strategy(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "match_id": uuid4(),
        "challenge_id": uuid4(),
        "user": "prisoner",
        "one_line_description": "Look at the assemble script.",
        "strategy": "Look at the assemble script.",
        "origin_strat_id": None,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class OneLineDescriptionTests(unittest.TestCase):
    def test_the_first_non_blank_line_becomes_the_label(self) -> None:
        self.assertEqual(
            one_line_description("\n\n  Read the script first.\nThen act."),
            "Read the script first.",
        )

    def test_a_single_line_is_kept_whole(self) -> None:
        self.assertEqual(one_line_description("Try the vault"), "Try the vault")

    def test_a_long_first_line_is_truncated_with_an_ellipsis(self) -> None:
        label = one_line_description("x" * 500)

        self.assertEqual(len(label), MAX_ONE_LINE_LENGTH)
        self.assertTrue(label.endswith("\u2026"))

    def test_truncation_does_not_leave_a_trailing_space_before_the_ellipsis(
        self,
    ) -> None:
        label = one_line_description("a" * (MAX_ONE_LINE_LENGTH - 1) + " b c")

        self.assertNotIn(" \u2026", label)


class SaveStrategyRequestTests(unittest.TestCase):
    def test_the_user_must_be_one_of_the_two_sides(self) -> None:
        with self.assertRaises(ValidationError):
            SaveStrategyRequest(match_id=uuid4(), user="system")

    def test_either_side_is_accepted(self) -> None:
        for user in ("prisoner", "warden"):
            self.assertEqual(
                SaveStrategyRequest(match_id=uuid4(), user=user).user, user
            )


class SaveStrategyRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unknown_match_is_not_found(self) -> None:
        with (
            patch.object(strategies_service, "find_for_match", AsyncMock()) as find,
            self.assertRaises(HTTPException) as raised,
        ):
            await save_strategy(
                SaveStrategyRequest(match_id=uuid4(), user="prisoner"),
                session=FakeSession(None),
            )

        self.assertEqual(raised.exception.status_code, 404)
        find.assert_not_awaited()

    async def test_a_match_without_that_sides_strategy_is_rejected(self) -> None:
        subject = match(strategy={})
        with (
            patch.object(
                strategies_service, "find_for_match", AsyncMock(return_value=None)
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            await save_strategy(
                SaveStrategyRequest(match_id=subject.id, user="prisoner"),
                session=FakeSession(subject),
            )

        self.assertEqual(raised.exception.status_code, 400)

    async def test_a_whitespace_only_strategy_is_not_saved(self) -> None:
        subject = match(strategy={"prisoner": "   \n  "})
        with (
            patch.object(
                strategies_service, "find_for_match", AsyncMock(return_value=None)
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            await save_strategy(
                SaveStrategyRequest(match_id=subject.id, user="prisoner"),
                session=FakeSession(subject),
            )

        self.assertEqual(raised.exception.status_code, 400)

    async def test_promotion_saves_the_matches_text_and_links_it_back(self) -> None:
        subject = match(strategy={"prisoner": "  Look at the assemble script.  "})
        saved = stored_strategy(
            match_id=subject.id,
            challenge_id=subject.challenge_id,
            strategy="Look at the assemble script.",
        )
        create = AsyncMock(return_value=saved)
        link = AsyncMock(return_value=True)
        with (
            patch.object(
                strategies_service, "find_for_match", AsyncMock(return_value=None)
            ),
            patch.object(strategies_service, "create_for_match", create),
            patch.object(matches_service, "set_match_strategy_id", link),
        ):
            answer = await save_strategy(
                SaveStrategyRequest(match_id=subject.id, user="prisoner"),
                session=FakeSession(subject),
            )

        self.assertEqual(answer.id, saved.id)
        self.assertEqual(answer.strategy, "Look at the assemble script.")
        # The text comes from the match row, trimmed, not from the request.
        self.assertEqual(
            create.await_args.kwargs["strategy"], "Look at the assemble script."
        )
        self.assertEqual(create.await_args.kwargs["match_id"], subject.id)
        self.assertEqual(create.await_args.kwargs["user"], "prisoner")
        # The saved row's id is written back onto the match.
        link.assert_awaited_once()
        self.assertEqual(link.await_args.args[1:], (subject.id, "prisoner", saved.id))

    async def test_asking_twice_does_not_insert_a_second_row(self) -> None:
        subject = match(strategy={"prisoner": "Look at the assemble script."})
        saved = stored_strategy(match_id=subject.id)
        create = AsyncMock()
        link = AsyncMock(return_value=True)
        with (
            patch.object(
                strategies_service,
                "find_for_match",
                AsyncMock(return_value=saved),
            ),
            patch.object(strategies_service, "create_for_match", create),
            patch.object(matches_service, "set_match_strategy_id", link),
        ):
            answer = await save_strategy(
                SaveStrategyRequest(match_id=subject.id, user="prisoner"),
                session=FakeSession(subject),
            )

        self.assertEqual(answer.id, saved.id)
        create.assert_not_awaited()
        # The link is still repaired, so a repeat fixes a missing id.
        link.assert_awaited_once()

    async def test_an_existing_row_is_returned_even_if_the_match_text_is_gone(
        self,
    ) -> None:
        """A promoted match that was later cleared still answers with its row."""
        subject = match(strategy=None)
        saved = stored_strategy(match_id=subject.id)
        with (
            patch.object(
                strategies_service, "find_for_match", AsyncMock(return_value=saved)
            ),
            patch.object(
                matches_service,
                "set_match_strategy_id",
                AsyncMock(return_value=True),
            ),
        ):
            answer = await save_strategy(
                SaveStrategyRequest(match_id=subject.id, user="prisoner"),
                session=FakeSession(subject),
            )

        self.assertEqual(answer.id, saved.id)


class ResolveStrategiesTests(unittest.IsolatedAsyncioTestCase):
    async def _resolve(self, **overrides: object) -> dict[str, str]:
        challenge_id = UUID(int=1)
        values: dict[str, object] = {
            "challenge_id": challenge_id,
            "prisoner_strategy_id": None,
            "prisoner_suggestions": None,
            "warden_strategy_id": None,
            "warden_suggestions": None,
        }
        values.update(overrides)
        with patch.object(
            strategies_service, "get_strategies", AsyncMock(return_value={})
        ):
            return await _resolve_strategies(session=None, **values)

    async def test_neither_side_strategised_gives_an_empty_mapping(self) -> None:
        self.assertEqual(await self._resolve(), {})

    async def test_free_text_suggestions_become_that_sides_strategy(self) -> None:
        resolved = await self._resolve(
            prisoner_suggestions="  Try the vault.  ",
            warden_suggestions="Watch the vault.",
        )

        self.assertEqual(
            resolved,
            {"prisoner": "Try the vault.", "warden": "Watch the vault."},
        )

    async def test_blank_suggestions_are_left_out_rather_than_emptied(self) -> None:
        self.assertEqual(await self._resolve(prisoner_suggestions="   "), {})

    async def test_a_library_strategy_is_used_verbatim(self) -> None:
        subject = match(strategy={"prisoner": "Look at the assemble script."})
        stored = stored_strategy(
            id=uuid4(),
            challenge_id=subject.challenge_id,
            strategy="Look at the assemble script.",
        )
        with patch.object(
            strategies_service,
            "get_strategies",
            AsyncMock(return_value={stored.id: stored}),
        ):
            resolved = await _resolve_strategies(
                session=None,
                challenge_id=subject.challenge_id,
                prisoner_strategy_id=stored.id,
                prisoner_suggestions=None,
                warden_strategy_id=None,
                warden_suggestions=None,
            )

        self.assertEqual(resolved, {"prisoner": stored.strategy})

    async def test_a_library_strategy_wins_over_free_text(self) -> None:
        """The explicit reference is the more specific request."""
        challenge_id = UUID(int=1)
        stored = stored_strategy(id=uuid4(), challenge_id=challenge_id)
        with patch.object(
            strategies_service,
            "get_strategies",
            AsyncMock(return_value={stored.id: stored}),
        ):
            resolved = await _resolve_strategies(
                session=None,
                challenge_id=challenge_id,
                prisoner_strategy_id=stored.id,
                prisoner_suggestions="ignored",
                warden_strategy_id=None,
                warden_suggestions=None,
            )

        self.assertEqual(resolved, {"prisoner": stored.strategy})

    async def test_an_unknown_strategy_id_is_not_found(self) -> None:
        with (
            patch.object(
                strategies_service, "get_strategies", AsyncMock(return_value={})
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            await _resolve_strategies(
                session=None,
                challenge_id=UUID(int=1),
                prisoner_strategy_id=UUID(int=99),
                prisoner_suggestions=None,
                warden_strategy_id=None,
                warden_suggestions=None,
            )

        self.assertEqual(raised.exception.status_code, 404)

    async def test_a_strategy_from_another_challenge_is_rejected(self) -> None:
        stored = stored_strategy(id=uuid4(), challenge_id=UUID(int=7))
        with (
            patch.object(
                strategies_service,
                "get_strategies",
                AsyncMock(return_value={stored.id: stored}),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            await _resolve_strategies(
                session=None,
                challenge_id=UUID(int=1),
                prisoner_strategy_id=stored.id,
                prisoner_suggestions=None,
                warden_strategy_id=None,
                warden_suggestions=None,
            )

        self.assertEqual(raised.exception.status_code, 400)

    async def test_both_library_ids_are_looked_up_in_one_query(self) -> None:
        challenge_id = UUID(int=1)
        first = stored_strategy(id=uuid4(), challenge_id=challenge_id, user="prisoner")
        second = stored_strategy(id=uuid4(), challenge_id=challenge_id, user="warden")
        lookup = AsyncMock(return_value={first.id: first, second.id: second})
        with patch.object(strategies_service, "get_strategies", lookup):
            resolved = await _resolve_strategies(
                session=None,
                challenge_id=challenge_id,
                prisoner_strategy_id=first.id,
                prisoner_suggestions=None,
                warden_strategy_id=second.id,
                warden_suggestions=None,
            )

        self.assertEqual(
            resolved, {"prisoner": first.strategy, "warden": second.strategy}
        )
        lookup.assert_awaited_once()
        # ``get_strategies(strategy_ids, session)``: the ids come first. Both
        # sides are fetched in one query rather than one call per id.
        self.assertEqual(set(lookup.await_args.args[0]), {first.id, second.id})
        self.assertIsNone(lookup.await_args.args[1])

    async def test_no_ids_means_no_lookup(self) -> None:
        lookup = AsyncMock(return_value={})
        with patch.object(strategies_service, "get_strategies", lookup):
            await _resolve_strategies(
                session=None,
                challenge_id=UUID(int=1),
                prisoner_strategy_id=None,
                prisoner_suggestions="a",
                warden_strategy_id=None,
                warden_suggestions=None,
            )

        # The service is still called, with an empty list, and short-circuits
        # to an empty result without touching the database. ``args[0]`` is the
        # id list: ``get_strategies(strategy_ids, session)``.
        self.assertEqual(lookup.await_args.args[0], [])


def strategy_row(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "match_id": uuid4(),
        "challenge_id": uuid4(),
        "user": "prisoner",
        "one_line_description": "Read the assemble script.",
        "strategy": "Read the assemble script first.",
        "origin_strat_id": None,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def match_row(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "challenge": SimpleNamespace(name="The Hidden Artifact"),
        "prisoner_model": "gpt-4o",
        "warden_model": "claude-sonnet-4.6",
        "winner": "prisoner",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def strategy_entry(**overrides: object) -> StrategyRow:
    """One library row as the service returns it: the strategy plus a name."""
    values: dict[str, object] = {
        "strategy": strategy_row(),
        "challenge_name": "The Hidden Artifact",
    }
    values.update(overrides)
    return StrategyRow(**values)


class StrategyLibraryTests(unittest.TestCase):
    """`GET /all` and the single-strategy lookup, over the real HTTP layer."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def list_all(self, **params: object) -> dict:
        with patch.object(
            strategies_service,
            "list_strategies",
            AsyncMock(return_value=([strategy_entry(), strategy_entry()], 9)),
        ):
            response = self.client.get("/api/v1/strategies/all", params=params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def get_one(self, strategy_id: object, **params: object) -> object:
        row = strategy_entry(strategy=strategy_row(id=strategy_id))
        parent = match_row(id=row.strategy.match_id)
        used = [match_row(), match_row()]
        with (
            patch.object(
                strategies_service,
                "get_strategy_row",
                AsyncMock(return_value=row),
            ),
            patch.object(matches_service, "get_match", AsyncMock(return_value=parent)),
            patch.object(
                matches_service,
                "list_matches_using_strategy",
                AsyncMock(return_value=(used, 5)),
            ) as lookup,
        ):
            response = self.client.get(
                "/api/v1/strategies",
                params={"strategy_id": str(strategy_id), **params},
            )
        self.assertEqual(response.status_code, 200)
        return response.json(), lookup

    def test_all_lists_the_library_newest_first(self) -> None:
        body = self.list_all()

        self.assertEqual(body["total"], 9)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["items"][0]["strategy"], "Read the assemble script first.")

    def test_all_pages_like_every_other_listing(self) -> None:
        body = self.list_all()

        self.assertEqual(
            set(body), {"items", "total", "offset", "limit", "has_more"}
        )
        self.assertTrue(body["has_more"])

    def test_all_defaults_to_the_shared_page_size(self) -> None:
        self.assertEqual(self.list_all()["limit"], DEFAULT_LIMIT)

    def test_all_carries_the_challenge_name(self) -> None:
        body = self.list_all()

        self.assertEqual(
            body["items"][0]["challenge_name"], "The Hidden Artifact"
        )
        self.assertIn("challenge_id", body["items"][0])

    def test_all_passes_its_window_through(self) -> None:
        with patch.object(
            strategies_service,
            "list_strategies",
            AsyncMock(return_value=([], 0)),
        ) as lookup:
            self.client.get(
                "/api/v1/strategies/all", params={"offset": 40, "limit": 10}
            )

        self.assertEqual(
            lookup.await_args.kwargs,
            {"offset": 40, "limit": 10, "challenge_id": None},
        )

    def test_all_filters_by_challenge_when_asked(self) -> None:
        challenge_id = uuid4()
        with patch.object(
            strategies_service,
            "list_strategies",
            AsyncMock(return_value=([], 0)),
        ) as lookup:
            response = self.client.get(
                "/api/v1/strategies/all",
                params={"challenge_id": str(challenge_id)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(lookup.await_args.kwargs["challenge_id"], challenge_id)

    def test_all_without_a_challenge_asks_for_every_challenge(self) -> None:
        with patch.object(
            strategies_service,
            "list_strategies",
            AsyncMock(return_value=([], 0)),
        ) as lookup:
            self.client.get("/api/v1/strategies/all")

        self.assertIsNone(lookup.await_args.kwargs["challenge_id"])

    def test_all_with_a_malformed_challenge_id_is_rejected(self) -> None:
        response = self.client.get(
            "/api/v1/strategies/all", params={"challenge_id": "not-a-uuid"}
        )

        self.assertEqual(response.status_code, 422)

    def test_all_refuses_a_limit_above_the_ceiling(self) -> None:
        response = self.client.get(
            "/api/v1/strategies/all", params={"limit": 9999}
        )

        self.assertEqual(response.status_code, 422)

    def test_an_unknown_strategy_is_not_found(self) -> None:
        with patch.object(
            strategies_service, "get_strategy_row", AsyncMock(return_value=None)
        ):
            response = self.client.get(
                "/api/v1/strategies", params={"strategy_id": str(uuid4())}
            )

        self.assertEqual(response.status_code, 404)

    def test_a_missing_strategy_id_is_rejected(self) -> None:
        response = self.client.get("/api/v1/strategies")

        self.assertEqual(response.status_code, 422)

    def test_the_lookup_returns_the_strategy_and_its_parent(self) -> None:
        strategy_id = uuid4()
        body, _ = self.get_one(strategy_id)

        self.assertEqual(body["strategy"]["id"], str(strategy_id))
        self.assertEqual(body["parent_match"]["match_id"], body["strategy"]["match_id"])
        self.assertEqual(
            body["parent_match"]["challenge_name"], "The Hidden Artifact"
        )

    def test_the_parent_is_excluded_from_the_matches_it_was_used_in(self) -> None:
        """The parent ran the wording before the strategy existed."""
        strategy_id = uuid4()
        body, lookup = self.get_one(strategy_id)

        self.assertEqual(
            str(lookup.await_args.kwargs["exclude_match_id"]),
            body["strategy"]["match_id"],
        )
        self.assertEqual(lookup.await_args.args[1], strategy_id)

    def test_the_used_in_list_reports_only_model_challenge_and_winner(self) -> None:
        """The lineage does not carry a match's history, just how to tell runs apart."""
        body, _ = self.get_one(uuid4())

        self.assertEqual(
            set(body["used_in_matches"]["items"][0]),
            {"match_id", "challenge_name", "prisoner_model", "warden_model", "winner"},
        )

    def test_the_used_in_list_is_paged_and_reports_the_real_total(self) -> None:
        body, _ = self.get_one(uuid4())

        used = body["used_in_matches"]
        self.assertEqual(used["total"], 5)
        self.assertEqual(len(used["items"]), 2)
        self.assertTrue(used["has_more"])
        self.assertEqual(used["offset"], 0)

    def test_the_used_in_window_is_passed_through(self) -> None:
        _, lookup = self.get_one(uuid4(), offset=3, limit=4)

        self.assertEqual(lookup.await_args.kwargs["offset"], 3)
        self.assertEqual(lookup.await_args.kwargs["limit"], 4)

    def test_a_deleted_challenge_leaves_the_name_null(self) -> None:
        """A missing challenge must not break the library or the lineage view."""
        row = strategy_entry(challenge_name=None)
        with (
            patch.object(
                strategies_service,
                "get_strategy_row",
                AsyncMock(return_value=row),
            ),
            patch.object(
                matches_service,
                "get_match",
                AsyncMock(return_value=match_row(challenge=None)),
            ),
            patch.object(
                matches_service,
                "list_matches_using_strategy",
                AsyncMock(return_value=([match_row(winner=None, challenge=None)], 1)),
            ),
        ):
            body = self.client.get(
                "/api/v1/strategies",
                params={"strategy_id": str(row.strategy.id)},
            ).json()

        self.assertIsNone(body["strategy"]["challenge_name"])
        self.assertIsNone(body["parent_match"]["challenge_name"])
        self.assertIsNone(body["used_in_matches"]["items"][0]["winner"])

    def test_a_library_row_without_a_challenge_still_lists(self) -> None:
        with patch.object(
            strategies_service,
            "list_strategies",
            AsyncMock(return_value=([strategy_entry(challenge_name=None)], 1)),
        ):
            body = self.client.get("/api/v1/strategies/all").json()

        self.assertIsNone(body["items"][0]["challenge_name"])


if __name__ == "__main__":
    unittest.main()
