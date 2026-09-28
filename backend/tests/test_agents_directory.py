"""The model directory: the provider/model catalogue every side is built from."""

import os
import unittest
from unittest.mock import patch

from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.agents.agents_directory import (
    PROVIDER_MODELS,
    PROVIDERS,
    ProviderSpec,
    build_agent,
    is_curated_model,
    join_model_name,
    models_for,
    resolve_model,
    resolve_provider,
)

#: Every offered pair, as ``(provider, model)``.
CATALOGUE = [
    (provider, model)
    for provider, models in PROVIDER_MODELS.items()
    for model in models
]


class CatalogueTests(unittest.TestCase):
    def test_only_the_offered_providers_are_present(self) -> None:
        self.assertEqual(
            set(PROVIDER_MODELS), {"openai", "anthropic", "google", "openrouter"}
        )
        self.assertEqual(set(PROVIDERS), set(PROVIDER_MODELS))

    def test_every_provider_offers_at_least_one_model(self) -> None:
        for provider, models in PROVIDER_MODELS.items():
            with self.subTest(provider=provider):
                self.assertGreaterEqual(len(models), 1)

    def test_the_catalogue_has_no_duplicate_pairs(self) -> None:
        self.assertEqual(len(CATALOGUE), len(set(CATALOGUE)))

    def test_models_for_returns_a_copy_and_tolerates_an_unknown_provider(
        self,
    ) -> None:
        models = models_for("openai")
        models.append("injected")
        self.assertNotIn("injected", PROVIDER_MODELS["openai"])
        self.assertEqual(models_for("nope"), [])


class JoinModelNameTests(unittest.TestCase):
    def test_every_catalogue_pair_joins(self) -> None:
        for provider, model in CATALOGUE:
            with self.subTest(provider=provider, model=model):
                self.assertEqual(
                    join_model_name(provider, model), f"{provider}:{model}"
                )

    def test_an_openrouter_model_keeps_its_slash(self) -> None:
        self.assertEqual(
            join_model_name("openrouter", "meta-llama/llama-3.3-70b-instruct"),
            "openrouter:meta-llama/llama-3.3-70b-instruct",
        )

    def test_a_pasted_model_under_a_known_provider_joins(self) -> None:
        """The curated list is suggestions; a pasted name is not rejected here.

        Whether the name is real is decided by ``check_model_exists`` against the
        provider, not by this function.
        """
        self.assertEqual(
            join_model_name("openai", "some-model-we-have-not-curated"),
            "openai:some-model-we-have-not-curated",
        )

    def test_an_unknown_provider_or_blank_model_is_rejected(self) -> None:
        for provider, model in (
            ("nope", "gpt-4o"),
            ("", "gpt-4o"),
            ("openai", ""),
            ("nvidia", "laguna-xs-2.1"),
        ):
            with self.subTest(provider=provider, model=model):
                self.assertIsNone(join_model_name(provider, model))

    def test_a_model_is_not_portable_between_providers(self) -> None:
        """The curated list is per provider, so membership does not carry over."""
        self.assertTrue(is_curated_model("openai", "gpt-4o"))
        self.assertFalse(is_curated_model("google", "gpt-4o"))


class ResolveProviderTests(unittest.TestCase):
    def test_provider_and_model_are_separated_without_a_key(self) -> None:
        spec, model_name = resolve_provider("openrouter:openai/gpt-4o")

        self.assertIs(spec.provider, OpenRouterProvider)
        self.assertIs(spec.model, OpenRouterModel)
        self.assertEqual(model_name, "openai/gpt-4o")

    def test_every_catalogue_name_resolves_to_its_provider_spec(self) -> None:
        for provider, model in CATALOGUE:
            with self.subTest(provider=provider, model=model):
                spec, model_name = resolve_provider(f"{provider}:{model}")

                self.assertIsInstance(spec, ProviderSpec)
                self.assertIs(spec, PROVIDERS[provider])
                self.assertEqual(model_name, model)

    def test_malformed_and_unknown_providers_are_rejected(self) -> None:
        for name in (
            "",
            "gpt-4o",
            "openai:",
            ":gpt-4o",
            "nope:gpt-4o",
            # A provider that is no longer wired up.
            "deepseek:deepseek-chat",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve_provider(name)

    def test_an_uncurated_model_still_resolves(self) -> None:
        """Building a client is not a validity check; the provider decides that."""
        spec, model_name = resolve_provider("openai:not-a-curated-model")

        self.assertIs(spec, PROVIDERS["openai"])
        self.assertEqual(model_name, "not-a-curated-model")


def configured_key(model: object) -> object:
    """The API key a built model's SDK client was constructed with.

    Providers differ: the OpenAI-compatible clients (OpenAI, OpenRouter) expose
    ``api_key`` directly, while the Google client nests it under
    ``_api_client``.
    """
    client = model.provider.client  # type: ignore[attr-defined]
    if hasattr(client, "api_key"):
        return client.api_key
    return client._api_client.api_key


class BuildAgentTests(unittest.TestCase):
    def test_every_catalogue_name_builds_an_agent(self) -> None:
        for provider, model in CATALOGUE:
            with self.subTest(provider=provider, model=model):
                self.assertIsInstance(
                    build_agent(f"{provider}:{model}", "test-key"), Agent
                )

    def test_the_supplied_key_reaches_the_provider_client(self) -> None:
        for provider, model in CATALOGUE:
            with self.subTest(provider=provider, model=model):
                agent = build_agent(f"{provider}:{model}", "sk-explicit-123")
                # ``Agent.model`` -> provider -> SDK client, as constructed.
                self.assertEqual(configured_key(agent.model), "sk-explicit-123")

    def test_an_environment_key_is_never_fallen_back_to(self) -> None:
        """The key is a parameter, so a host env var must not be picked up."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=False):
            agent = build_agent("openai:gpt-4o-mini", "explicit-key")

        self.assertEqual(configured_key(agent.model), "explicit-key")


class ResolveModelTests(unittest.TestCase):
    def test_a_catalogue_name_resolves_with_the_callers_key(self) -> None:
        model = resolve_model("openai:gpt-4o-mini", "sk-byok")

        self.assertEqual(configured_key(model), "sk-byok")

    def test_a_missing_key_is_rejected(self) -> None:
        """Every model is BYOK, so there is no keyless path to resolve."""
        for api_key in (None, ""):
            with self.subTest(api_key=api_key):
                with self.assertRaises(ValueError):
                    resolve_model("openai:gpt-4o-mini", api_key)

    def test_an_unknown_provider_is_rejected_even_with_a_key(self) -> None:
        with self.assertRaises(ValueError):
            resolve_model("nope:gpt-4o", "sk-byok")

    def test_an_uncurated_model_is_built_rather_than_rejected(self) -> None:
        """Existence is the provider's call, made by ``check_model_exists``."""
        model = resolve_model("openai:a-model-we-have-not-curated", "sk-byok")

        self.assertEqual(configured_key(model), "sk-byok")
