"""Where a BYOK key can outlive the request that carried it.

The store is encrypted and TTL'd, so nothing here is a plaintext leak. What
these pin is *promptness*: a key written for a match that then fails to be
created or queued has no owner and would otherwise sit in Redis for the whole
TTL, and a key echoed back in a 422 response body is a copy of a credential the
caller did not ask to receive.

Both start routes store keys the same way -- store both sides, write the match
row, enqueue -- so both are covered.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import SecretStr

from app.api.app import is_secret_body_field, scrub_secret_validation_errors
from app.api.routes import matches
from app.api.schemas.dto_models import StartForkMatchRequest, StartMatchRequest
from app.db.services.match_fork_service import READY as FORK_READY
from app.secrets import ByokStoreError

CHALLENGE_ID = uuid4()


def start_payload() -> StartMatchRequest:
    return StartMatchRequest(
        challenge_id=CHALLENGE_ID,
        prisoner_provider="openai",
        prisoner_model="gpt-4o-mini",
        warden_provider="openai",
        warden_model="gpt-4o-mini",
        prisoner_api_key=SecretStr("sk-prisoner"),
        warden_api_key=SecretStr("sk-warden"),
    )


def fork_payload() -> StartForkMatchRequest:
    return StartForkMatchRequest(
        fork_id=uuid4(),
        prisoner_provider="openai",
        prisoner_model="gpt-4o-mini",
        warden_provider="openai",
        warden_model="gpt-4o-mini",
        prisoner_api_key=SecretStr("sk-prisoner"),
        warden_api_key=SecretStr("sk-warden"),
    )


class KeyCleanupTestCase(unittest.IsolatedAsyncioTestCase):
    """Records every discard the route performs, and stubs its collaborators."""

    def setUp(self) -> None:
        self.discarded: list[object] = []

        async def record_discard(match_id: object) -> None:
            self.discarded.append(match_id)

        patcher = patch.object(matches, "_discard_byok_keys", record_discard)
        patcher.start()
        self.addCleanup(patcher.stop)

    def patch_common(self, **overrides: object) -> None:
        """The route's collaborators, minus whatever a test is probing."""
        collaborators: dict[str, object] = {
            "_resolve_strategies": AsyncMock(return_value={}),
            "_resolve_side": AsyncMock(return_value="sk-plain"),
            "store_api_key": AsyncMock(),
            "run_in_threadpool": AsyncMock(),
        }
        collaborators.update(overrides)
        for name, value in collaborators.items():
            patcher = patch.object(matches, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def failing_store(*, fail_on: str) -> tuple[object, list[str]]:
        """A store that records what landed and fails on the named side."""
        stored: list[str] = []

        async def store(match_id: object, actor: str, key: str) -> None:
            if actor == fail_on:
                raise ByokStoreError("redis went away")
            stored.append(actor)

        return store, stored


class StartMatchKeyCleanupTests(KeyCleanupTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.session = AsyncMock()
        self.session.get = AsyncMock(
            return_value=SimpleNamespace(id=CHALLENGE_ID, win_condition="w")
        )

    async def test_a_queued_match_keeps_its_keys_for_the_worker(self) -> None:
        """The happy path must NOT discard: the worker redeems these."""
        self.patch_common()
        with patch.object(
            matches.matches_service, "create_queued_match", AsyncMock()
        ):
            response = await matches.start_match(
                start_payload(), session=self.session
            )

        self.assertEqual(response.status, "queued")
        self.assertEqual(self.discarded, [])

    async def test_a_half_stored_pair_is_removed_immediately(self) -> None:
        """The Prisoner's key lands, then the Warden's store fails."""
        store, stored = self.failing_store(fail_on="warden")
        self.patch_common(store_api_key=store)

        with self.assertRaises(HTTPException) as raised:
            await matches.start_match(start_payload(), session=self.session)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(stored, ["prisoner"])
        self.assertEqual(len(self.discarded), 1)

    async def test_a_match_row_that_cannot_be_written_drops_the_keys(self) -> None:
        """Nothing will ever redeem them once the write fails."""
        self.patch_common()
        with (
            patch.object(
                matches.matches_service,
                "create_queued_match",
                AsyncMock(side_effect=RuntimeError("database is gone")),
            ),
            self.assertRaises(RuntimeError),
        ):
            await matches.start_match(start_payload(), session=self.session)

        self.assertEqual(len(self.discarded), 1)

    async def test_a_queue_that_cannot_be_reached_drops_the_keys(self) -> None:
        """Pre-existing behaviour, pinned so it stays."""
        self.patch_common(
            run_in_threadpool=AsyncMock(side_effect=RuntimeError("broker is gone"))
        )
        with (
            patch.object(
                matches.matches_service, "create_queued_match", AsyncMock()
            ),
            patch.object(matches.matches_service, "set_status", AsyncMock()),
            self.assertRaises(HTTPException) as raised,
        ):
            await matches.start_match(start_payload(), session=self.session)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(len(self.discarded), 1)


class ForkStartKeyCleanupTests(KeyCleanupTestCase):
    """``start-from-fork`` stores keys the same way and needs the same cleanup."""

    def setUp(self) -> None:
        super().setUp()
        self.session = AsyncMock()
        self.fork = SimpleNamespace(
            id=uuid4(),
            parent_match_id=uuid4(),
            branch_event_id=uuid4(),
            status=FORK_READY,
        )
        self.parent = SimpleNamespace(
            id=self.fork.parent_match_id,
            challenge_id=CHALLENGE_ID,
            win_condition="w",
        )

    def patch_fork_lookups(self) -> None:
        for target, name, value in (
            (matches.match_forks_service, "get_fork", AsyncMock(return_value=self.fork)),
            (matches.matches_service, "get_match", AsyncMock(return_value=self.parent)),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_a_half_stored_pair_is_removed_immediately(self) -> None:
        self.patch_fork_lookups()
        store, stored = self.failing_store(fail_on="warden")
        self.patch_common(store_api_key=store)

        with self.assertRaises(HTTPException) as raised:
            await matches.start_from_fork(fork_payload(), session=self.session)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(stored, ["prisoner"])
        self.assertEqual(len(self.discarded), 1)

    async def test_a_match_row_that_cannot_be_written_drops_the_keys(self) -> None:
        self.patch_fork_lookups()
        self.patch_common()
        with (
            patch.object(
                matches.matches_service,
                "create_queued_match",
                AsyncMock(side_effect=RuntimeError("database is gone")),
            ),
            self.assertRaises(RuntimeError),
        ):
            await matches.start_from_fork(fork_payload(), session=self.session)

        self.assertEqual(len(self.discarded), 1)


class ValidationErrorScrubbingTests(unittest.TestCase):
    """A 422 must not hand back the credential that caused it."""

    def test_every_api_key_field_name_is_treated_as_a_credential(self) -> None:
        for name in ("api_key", "prisoner_api_key", "warden_api_key", "future_api_key"):
            with self.subTest(field=name):
                self.assertTrue(is_secret_body_field(name))

    def test_an_ordinary_field_is_not(self) -> None:
        for name in ("provider", "model", "strategy_id", "api_keys", "my_api_key_id"):
            with self.subTest(field=name):
                self.assertFalse(is_secret_body_field(name))

    def test_the_plain_api_key_field_is_scrubbed(self) -> None:
        """``verify-model`` and the review both name it plain ``api_key``.

        That is the field the old hard-coded pair of names missed, so a
        malformed request to either route echoed the credential back.
        """
        scrubbed = scrub_secret_validation_errors(
            [
                {
                    "type": "string_type",
                    "loc": ("body", "api_key"),
                    "msg": "Input should be a valid string",
                    "input": {"nested": "sk-must-not-be-echoed"},
                }
            ]
        )

        self.assertNotIn("input", scrubbed[0])
        self.assertEqual(scrubbed[0]["loc"], ("body", "api_key"))

    def test_the_two_side_fields_are_still_scrubbed(self) -> None:
        scrubbed = scrub_secret_validation_errors(
            [
                {
                    "type": "string_type",
                    "loc": ("body", "warden_api_key"),
                    "msg": "x",
                    "input": "sk-must-not-be-echoed",
                }
            ]
        )

        self.assertNotIn("input", scrubbed[0])

    def test_other_fields_keep_the_standard_detail(self) -> None:
        scrubbed = scrub_secret_validation_errors(
            [
                {
                    "type": "missing",
                    "loc": ("body", "challenge_id"),
                    "msg": "Field required",
                    "input": {"anything": True},
                }
            ]
        )

        self.assertEqual(scrubbed[0]["input"], {"anything": True})


if __name__ == "__main__":
    unittest.main()


class ReviewEndpointStorageTests(unittest.TestCase):
    """The review runs inline, so its key is never stored and never redeemed.

    There is no worker on the other side of a queue to hand it to: the agent is
    built and run inside the request. That means there is nothing to delete
    afterwards, and it also means the route must not reach for the store --
    a key written for a review would have no match id to expire against and
    nothing that would ever take it.
    """

    def test_the_review_route_never_touches_the_key_store(self) -> None:
        import inspect

        from app.api.routes import strategy_review

        source = inspect.getsource(strategy_review)
        self.assertNotIn("store_api_key", source)
        self.assertNotIn("discard_api_keys", source)
