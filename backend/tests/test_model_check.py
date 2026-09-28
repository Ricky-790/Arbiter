"""Confirming a pasted model name with its provider.

Offline: every provider listing is stubbed, so these cover the decisions that
matter — what counts as "not found" versus "could not ask", that a missing key
never reaches a provider, and that the result is cached without retaining the
key. The one thing they cannot cover is whether a real provider's list actually
contains a given name; that is what the stubs stand in for.
"""

import time
import types
import unittest
from unittest.mock import patch

from app.agents import agents_directory as directory
from app.agents.agents_directory import ModelCheckError, check_model_exists


class _AuthError(Exception):
    """Stands in for a provider SDK's authentication failure."""

    status_code = 401


class CheckModelExistsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # The cache is module state and would otherwise leak between tests.
        directory._check_cache.clear()

    async def test_a_served_model_is_accepted(self) -> None:
        async def lister(api_key: str) -> set[str]:
            return {"gpt-4o", "gpt-4o-mini"}

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            await check_model_exists("openai", "gpt-4o", "sk")

    async def test_a_missing_model_is_reported_as_not_found(self) -> None:
        async def lister(api_key: str) -> set[str]:
            return {"gpt-4o"}

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            with self.assertRaises(ModelCheckError) as raised:
                await check_model_exists("openai", "gpt-4o-mini", "sk")

        self.assertEqual(raised.exception.reason, "not_found")
        self.assertIn("gpt-4o-mini", raised.exception.detail)

    async def test_a_refused_key_is_reported_as_key_rejected(self) -> None:
        async def lister(api_key: str) -> set[str]:
            raise _AuthError("nope")

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            with self.assertRaises(ModelCheckError) as raised:
                await check_model_exists("openai", "gpt-4o", "sk")

        self.assertEqual(raised.exception.reason, "key_rejected")

    async def test_any_other_failure_is_reported_as_unreachable(self) -> None:
        async def lister(api_key: str) -> set[str]:
            raise TimeoutError("took too long")

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            with self.assertRaises(ModelCheckError) as raised:
                await check_model_exists("openai", "gpt-4o", "sk")

        self.assertEqual(raised.exception.reason, "unreachable")

    async def test_a_provider_error_message_never_reaches_the_caller(self) -> None:
        """Provider text can echo the request URL, which may carry the key."""

        async def lister(api_key: str) -> set[str]:
            raise RuntimeError("GET https://api.example/models?key=sk-super-secret")

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            with self.assertRaises(ModelCheckError) as raised:
                await check_model_exists("openai", "gpt-4o", "sk-super-secret")

        self.assertNotIn("sk-super-secret", raised.exception.detail)
        self.assertNotIn("sk-super-secret", str(raised.exception))

    async def test_an_unknown_provider_is_not_found_without_a_call(self) -> None:
        with self.assertRaises(ModelCheckError) as raised:
            await check_model_exists("nvidia", "laguna-xs-2.1", "sk")

        self.assertEqual(raised.exception.reason, "not_found")

    async def test_a_blank_model_is_rejected_without_a_call(self) -> None:
        with self.assertRaises(ModelCheckError) as raised:
            await check_model_exists("openai", "", "sk")

        self.assertEqual(raised.exception.reason, "not_found")


class CheckCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        directory._check_cache.clear()

    async def test_a_successful_check_is_not_repeated(self) -> None:
        """The UI verifies as the operator types, then start-match verifies again."""
        calls = 0

        async def lister(api_key: str) -> set[str]:
            nonlocal calls
            calls += 1
            return {"gpt-4o"}

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            await check_model_exists("openai", "gpt-4o", "sk")
            await check_model_exists("openai", "gpt-4o", "sk")

        self.assertEqual(calls, 1)

    async def test_a_failed_check_is_not_cached(self) -> None:
        """An operator fixing a wrong key must not be shown the old verdict."""
        calls = 0

        async def lister(api_key: str) -> set[str]:
            nonlocal calls
            calls += 1
            return {"gpt-4o"}

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            for _ in range(2):
                with self.assertRaises(ModelCheckError):
                    await check_model_exists("openai", "not-a-model", "sk")

        self.assertEqual(calls, 2)

    async def test_a_different_key_is_checked_separately(self) -> None:
        calls = 0

        async def lister(api_key: str) -> set[str]:
            nonlocal calls
            calls += 1
            return {"gpt-4o"}

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            await check_model_exists("openai", "gpt-4o", "sk-one")
            await check_model_exists("openai", "gpt-4o", "sk-two")

        self.assertEqual(calls, 2)

    async def test_no_api_key_is_retained_in_the_cache(self) -> None:
        async def lister(api_key: str) -> set[str]:
            return {"gpt-4o"}

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            await check_model_exists("openai", "gpt-4o", "sk-super-secret")

        retained = " ".join(str(entry) for entry in directory._check_cache)
        self.assertNotIn("sk-super-secret", retained)

    async def test_expired_entries_are_evicted(self) -> None:
        """A long-lived worker must not accumulate every model ever checked."""

        async def lister(api_key: str) -> set[str]:
            return {"gpt-4o"}

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            await check_model_exists("openai", "gpt-4o", "sk")
            for key in list(directory._check_cache):
                directory._check_cache[key] = time.monotonic() - 1
            # Any later successful check prunes what has expired.
            await check_model_exists("openai", "gpt-4o", "another-key")

        self.assertEqual(len(directory._check_cache), 1)

    async def test_an_expired_entry_is_checked_again(self) -> None:
        calls = 0

        async def lister(api_key: str) -> set[str]:
            nonlocal calls
            calls += 1
            return {"gpt-4o"}

        with patch.dict(directory._MODEL_LISTERS, {"openai": lister}):
            await check_model_exists("openai", "gpt-4o", "sk")
            # Age every entry past its TTL.
            for key in list(directory._check_cache):
                directory._check_cache[key] = time.monotonic() - 1
            await check_model_exists("openai", "gpt-4o", "sk")

        self.assertEqual(calls, 2)


class ProviderListingTests(unittest.IsolatedAsyncioTestCase):
    """The listers parse a provider's real response shape, which is easy to get wrong."""

    async def test_google_names_lose_their_models_prefix(self) -> None:
        class FakeModel:
            def __init__(self, name: str) -> None:
                self.name = name

        class FakePager:
            def __aiter__(self):
                async def generate():
                    for name in ("models/gemini-2.5-flash", "models/gemini-2.5-pro"):
                        yield FakeModel(name)

                return generate()

        class FakeModels:
            async def list(self):
                return FakePager()

        class FakeAio:
            models = FakeModels()

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                self.aio = FakeAio()

        google_pkg = types.ModuleType("google")
        google_genai = types.ModuleType("google.genai")
        google_genai.Client = FakeClient  # type: ignore[attr-defined]
        google_pkg.genai = google_genai  # type: ignore[attr-defined]

        with patch.dict(
            "sys.modules", {"google": google_pkg, "google.genai": google_genai}
        ):
            names = await directory._list_google_models("sk")

        self.assertEqual(names, {"gemini-2.5-flash", "gemini-2.5-pro"})

    async def test_openrouter_is_listed_over_its_own_base_url(self) -> None:
        seen: dict[str, object] = {}

        class FakeModel:
            def __init__(self, id: str) -> None:
                self.id = id

        class FakePaginator:
            def __aiter__(self):
                async def generate():
                    yield FakeModel("openai/gpt-4o")

                return generate()

        class FakeModels:
            async def list(self):
                return FakePaginator()

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                seen.update(kwargs)
                self.models = FakeModels()

        fake_openai = type("openai", (), {"AsyncOpenAI": FakeClient})

        with patch.dict("sys.modules", {"openai": fake_openai}):
            names = await directory._list_openai_compatible_models("openrouter", "sk")

        self.assertEqual(names, {"openai/gpt-4o"})
        self.assertEqual(seen["base_url"], "https://openrouter.ai/api/v1")


if __name__ == "__main__":
    unittest.main()
