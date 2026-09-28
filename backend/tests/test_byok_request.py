"""BYOK plumbing between the request body and the agent the worker builds.

Offline: the store is stubbed. These cover the rules that decide whether a key
is required, that the request body is validated against the model directory, and
that a match refuses to start when its key is gone.

Every model is BYOK, so there is no keyless path left to test.
"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import SecretStr

from app.agents.agents_directory import ModelCheckError
from app.broker.models import MatchStartMessage
from app.workers.match_worker import redeem_byok_key

PROVIDER = "openai"
MODEL = "gpt-4o-mini"


class ResolveSideTests(unittest.IsolatedAsyncioTestCase):
    """``_resolve_side`` is the gate between the body and the key store.

    The provider check is stubbed throughout: these are about the route's
    decisions, and the check itself is covered by ``test_model_check``.
    """

    def setUp(self) -> None:
        # Imported here so the API package is only loaded for these tests.
        from app.api.routes import matches

        self.matches = matches
        self.resolve = matches._resolve_side

    async def test_a_valid_pair_returns_the_supplied_key(self) -> None:
        with patch.object(self.matches, "check_model_exists", new=AsyncMock()):
            key = await self.resolve(
                PROVIDER, MODEL, SecretStr(" sk-byok "), "prisoner"
            )

        self.assertEqual(key, "sk-byok")

    async def test_a_missing_key_is_rejected_for_every_model(self) -> None:
        check = AsyncMock()
        with patch.object(self.matches, "check_model_exists", new=check):
            for missing in (None, SecretStr(""), SecretStr("   ")):
                with self.subTest(missing=missing):
                    with self.assertRaises(HTTPException) as raised:
                        await self.resolve(PROVIDER, MODEL, missing, "warden")

                    self.assertEqual(raised.exception.status_code, 400)
                    self.assertIn("warden_api_key", raised.exception.detail)

        # No key means nothing to read the provider's model list with.
        check.assert_not_awaited()

    async def test_an_unknown_provider_is_rejected(self) -> None:
        check = AsyncMock()
        with patch.object(self.matches, "check_model_exists", new=check):
            with self.assertRaises(HTTPException) as raised:
                await self.resolve("nope", MODEL, SecretStr("sk"), "prisoner")

        self.assertEqual(raised.exception.status_code, 400)
        check.assert_not_awaited()

    async def test_a_model_the_provider_does_not_serve_is_rejected(self) -> None:
        error = ModelCheckError("not_found", "openai does not offer 'nope'")
        with patch.object(
            self.matches, "check_model_exists", new=AsyncMock(side_effect=error)
        ):
            with self.assertRaises(HTTPException) as raised:
                await self.resolve(PROVIDER, "nope", SecretStr("sk"), "prisoner")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("does not offer", raised.exception.detail)
        self.assertIn("prisoner", raised.exception.detail)

    async def test_an_unreachable_provider_fails_closed(self) -> None:
        """An unconfirmed name could still take a sandbox, so it is refused."""
        error = ModelCheckError("unreachable", "Could not reach openai")
        with patch.object(
            self.matches, "check_model_exists", new=AsyncMock(side_effect=error)
        ):
            with self.assertRaises(HTTPException) as raised:
                await self.resolve(PROVIDER, MODEL, SecretStr("sk"), "warden")

        self.assertEqual(raised.exception.status_code, 400)

    async def test_a_refused_key_is_rejected(self) -> None:
        error = ModelCheckError("key_rejected", "openai rejected this API key")
        with patch.object(
            self.matches, "check_model_exists", new=AsyncMock(side_effect=error)
        ):
            with self.assertRaises(HTTPException) as raised:
                await self.resolve(PROVIDER, MODEL, SecretStr("sk"), "prisoner")

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
    def test_the_message_carries_no_key_of_its_own(self) -> None:
        """Keys travel by reference through the store, never on the queue."""
        fields = set(MatchStartMessage.model_fields)

        self.assertNotIn("prisoner_api_key", fields)
        self.assertNotIn("warden_api_key", fields)

    def test_the_message_carries_the_split_provider_and_model(self) -> None:
        message = MatchStartMessage(
            match_id="00000000-0000-0000-0000-000000000001",
            challenge_id="00000000-0000-0000-0000-000000000002",
            prisoner_provider=PROVIDER,
            prisoner_model=MODEL,
            warden_provider="google",
            warden_model="gemini-2.0-flash",
        )

        self.assertEqual(message.prisoner_provider, PROVIDER)
        self.assertEqual(message.prisoner_model, MODEL)


class RedeemByokKeyTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_side_reads_its_key_out_of_the_store(self) -> None:
        sentinel = "00000000-0000-0000-0000-000000000003"

        async def fake_take(match_id: object, side: str) -> str:
            self.assertEqual((str(match_id), side), (sentinel, "warden"))
            return "sk-redeemed"

        with patch("app.workers.match_worker.take_api_key", fake_take):
            key = await redeem_byok_key(sentinel, "warden")

        self.assertEqual(key, "sk-redeemed")

    async def test_an_expired_key_fails_the_match_rather_than_falling_back(
        self,
    ) -> None:
        async def nothing_stored(*args: object) -> None:
            return None

        with patch("app.workers.match_worker.take_api_key", nothing_stored):
            with self.assertRaises(RuntimeError) as raised:
                await redeem_byok_key("match-1", "prisoner")

        self.assertIn("not found", str(raised.exception))
