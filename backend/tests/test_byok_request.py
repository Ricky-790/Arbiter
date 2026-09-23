"""BYOK plumbing between the request body and the agent the worker builds.

Offline: the store is stubbed, so these cover the rules that decide whether a
key is required, that it is never passed for a free model, and that a match
refuses to start when its key is gone.
"""

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import SecretStr

from app.broker.models import MatchStartMessage
from app.workers.match_worker import redeem_byok_key

FREE_MODEL = "nvidia/laguna-xs-2.1"
BYOK_MODEL = "openai:gpt-4o-mini"


class ByokRequestFieldTests(unittest.TestCase):
    """``_byok_key`` is the gate between the body and the key store."""

    def setUp(self) -> None:
        # Imported here so the API package is only loaded for these tests.
        from app.api.routes.matches import _byok_key

        self.byok_key = _byok_key

    def test_a_free_model_needs_no_key(self) -> None:
        self.assertIsNone(self.byok_key(FREE_MODEL, None, "prisoner"))

    def test_a_key_sent_for_a_free_model_is_dropped_not_stored(self) -> None:
        """The key is unnecessary, so it must not reach the store."""
        self.assertIsNone(
            self.byok_key(FREE_MODEL, SecretStr("sk-unnecessary"), "prisoner")
        )

    def test_a_byok_model_returns_the_supplied_key(self) -> None:
        self.assertEqual(
            self.byok_key(BYOK_MODEL, SecretStr(" sk-byok "), "prisoner"), "sk-byok"
        )

    def test_a_byok_model_without_a_key_is_rejected(self) -> None:
        for missing in (None, SecretStr(""), SecretStr("   ")):
            with self.subTest(missing=missing):
                with self.assertRaises(HTTPException) as raised:
                    self.byok_key(BYOK_MODEL, missing, "warden")

                self.assertEqual(raised.exception.status_code, 400)
                self.assertIn("warden_api_key", raised.exception.detail)

    def test_an_unknown_model_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self.byok_key("nope:gpt-4o", None, "prisoner")

        self.assertEqual(raised.exception.status_code, 400)


class ValidationErrorScrubbingTests(unittest.TestCase):
    """FastAPI echoes the offending input in a 422; a credential must not be."""

    def test_a_credential_value_is_never_echoed_back(self) -> None:
        from app.api.app import scrub_secret_validation_errors

        scrubbed = scrub_secret_validation_errors(
            [
                {
                    "type": "string_type",
                    "loc": ("body", "prisoner_api_key"),
                    "msg": "Input should be a valid string",
                    "input": {"nested": "sk-must-not-be-echoed"},
                },
                {
                    "type": "missing",
                    "loc": ("body", "challenge_id"),
                    "msg": "Field required",
                    "input": {"anything": True},
                },
            ]
        )

        self.assertNotIn("input", scrubbed[0])
        self.assertEqual(scrubbed[0]["loc"], ("body", "prisoner_api_key"))
        self.assertEqual(scrubbed[0]["msg"], "Input should be a valid string")
        # Every other field keeps the standard FastAPI detail.
        self.assertEqual(scrubbed[1]["input"], {"anything": True})


class MatchStartMessageTests(unittest.TestCase):
    def test_byok_defaults_to_off(self) -> None:
        message = MatchStartMessage(
            match_id="00000000-0000-0000-0000-000000000001",
            challenge_id="00000000-0000-0000-0000-000000000002",
            prisoner_model=FREE_MODEL,
            warden_model=FREE_MODEL,
        )

        self.assertFalse(message.prisoner_byok)
        self.assertFalse(message.warden_byok)

    def test_the_message_carries_no_key_of_its_own(self) -> None:
        fields = set(MatchStartMessage.model_fields)

        self.assertNotIn("prisoner_api_key", fields)
        self.assertNotIn("warden_api_key", fields)


class RedeemByokKeyTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_free_side_never_touches_the_store(self) -> None:
        async def explode(*args: object) -> str:
            raise AssertionError("the store must not be read for a free model")

        with patch("app.workers.match_worker.take_api_key", explode):
            self.assertIsNone(await redeem_byok_key("match-1", "prisoner", False))

    async def test_a_byok_side_reads_its_key_out(self) -> None:
        sentinel = "00000000-0000-0000-0000-000000000003"

        async def fake_take(match_id: object, side: str) -> str:
            self.assertEqual((str(match_id), side), (sentinel, "warden"))
            return "sk-redeemed"

        with patch("app.workers.match_worker.take_api_key", fake_take):
            key = await redeem_byok_key(sentinel, "warden", True)

        self.assertEqual(key, "sk-redeemed")

    async def test_an_expired_key_fails_the_match_rather_than_falling_back(
        self,
    ) -> None:
        async def nothing_stored(*args: object) -> None:
            return None

        with patch("app.workers.match_worker.take_api_key", nothing_stored):
            with self.assertRaises(RuntimeError) as raised:
                await redeem_byok_key("match-1", "prisoner", True)

        self.assertIn("BYOK key", str(raised.exception))
