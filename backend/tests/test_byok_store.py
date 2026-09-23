"""The short-lived BYOK key store.

Offline: the Redis client is replaced with an in-memory stand-in, so these pin
the guarantees the API/worker handoff relies on -- encrypted at rest, deleted on
read, unused entries expiring, and a clear failure when the deployment secret
is missing or has changed.
"""

import os
import unittest
from unittest.mock import patch

from app.secrets.byok_store import (
    DEFAULT_TTL_SECONDS,
    PRISONER,
    WARDEN,
    ByokStoreError,
    discard_api_keys,
    store_api_key,
    take_api_key,
    ttl_seconds,
)


class FakeRedis:
    """The subset of ``redis.asyncio.Redis`` the store uses."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int | None] = {}

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.values[key] = value
        self.expirations[key] = ex

    async def getdel(self, key: str) -> str | None:
        self.expirations.pop(key, None)
        return self.values.pop(key, None)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.expirations.pop(key, None)


class ByokStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        self._env = dict(os.environ)
        os.environ["ARBITER_BYOK_SECRET"] = "unit-test-secret"
        self.patch_redis = patch(
            "app.secrets.byok_store.get_async_redis", return_value=self.redis
        )
        self.patch_redis.start()

    def tearDown(self) -> None:
        self.patch_redis.stop()
        os.environ.clear()
        os.environ.update(self._env)

    def stored_tokens(self) -> list[str]:
        return list(self.redis.values.values())

    async def test_a_stored_key_comes_back_out(self) -> None:
        await store_api_key("match-1", PRISONER, "sk-secret-value")

        self.assertEqual(await take_api_key("match-1", PRISONER), "sk-secret-value")

    async def test_the_stored_bytes_are_not_the_plaintext_key(self) -> None:
        await store_api_key("match-1", WARDEN, "sk-secret-value")

        for token in self.stored_tokens():
            self.assertNotIn("sk-secret-value", token)

    async def test_the_key_is_deleted_as_it_is_read(self) -> None:
        await store_api_key("match-1", PRISONER, "sk-once")

        self.assertEqual(await take_api_key("match-1", PRISONER), "sk-once")
        self.assertIsNone(await take_api_key("match-1", PRISONER))
        self.assertEqual(self.redis.values, {})

    async def test_a_missing_entry_reads_as_none(self) -> None:
        self.assertIsNone(await take_api_key("match-never-queued", PRISONER))

    async def test_sides_and_matches_do_not_share_entries(self) -> None:
        await store_api_key("match-1", PRISONER, "prisoner-key")
        await store_api_key("match-1", WARDEN, "warden-key")
        await store_api_key("match-2", PRISONER, "other-match-key")

        self.assertEqual(await take_api_key("match-1", WARDEN), "warden-key")
        self.assertEqual(await take_api_key("match-2", PRISONER), "other-match-key")
        self.assertEqual(await take_api_key("match-1", PRISONER), "prisoner-key")

    async def test_discarding_clears_both_sides_of_one_match(self) -> None:
        await store_api_key("match-1", PRISONER, "prisoner-key")
        await store_api_key("match-1", WARDEN, "warden-key")
        await store_api_key("match-2", PRISONER, "other-match-key")

        await discard_api_keys("match-1")

        self.assertIsNone(await take_api_key("match-1", PRISONER))
        self.assertIsNone(await take_api_key("match-1", WARDEN))
        self.assertEqual(await take_api_key("match-2", PRISONER), "other-match-key")

    async def test_entries_expire_so_an_unstarted_match_leaves_nothing(self) -> None:
        await store_api_key("match-1", PRISONER, "sk-secret-value")

        self.assertEqual(self.redis.expirations, {"arbiter:byok:match-1:prisoner": 3600})

    async def test_an_empty_key_is_never_stored(self) -> None:
        with self.assertRaises(ByokStoreError):
            await store_api_key("match-1", PRISONER, "")

        self.assertEqual(self.redis.values, {})

    async def test_a_missing_deployment_secret_refuses_to_store(self) -> None:
        with patch.dict(os.environ, {"ARBITER_BYOK_SECRET": ""}):
            with self.assertRaises(ByokStoreError):
                await store_api_key("match-1", PRISONER, "sk-secret-value")

    async def test_a_rotated_deployment_secret_cannot_be_read_back(self) -> None:
        await store_api_key("match-1", PRISONER, "sk-secret-value")

        with patch.dict(os.environ, {"ARBITER_BYOK_SECRET": "rotated"}):
            with self.assertRaises(ByokStoreError):
                await take_api_key("match-1", PRISONER)

    async def test_the_ttl_configuration_is_validated(self) -> None:
        self.assertEqual(ttl_seconds(), DEFAULT_TTL_SECONDS)
        for raw in ("120", "nonsense", "0", "-5", ""):
            with self.subTest(raw=raw):
                with patch.dict(os.environ, {"ARBITER_BYOK_TTL_SECONDS": raw}):
                    expected = 120 if raw == "120" else DEFAULT_TTL_SECONDS
                    self.assertEqual(ttl_seconds(), expected)
