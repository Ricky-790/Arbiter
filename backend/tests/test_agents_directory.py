"""The model directory: free models and BYOK model construction."""

import os
import unittest
from unittest.mock import patch

from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.agents.agents_directory import (
    BYOK_MODEL_NAMES,
    PROVIDERS,
    ProviderSpec,
    agent_mapper,
    build_agent,
    is_byok_model,
    resolve_byok_provider,
    resolve_model,
    split_model_name,
)


class ByokCatalogueTests(unittest.TestCase):
    def test_catalogue_covers_the_requested_providers(self) -> None:
        counts: dict[str, int] = {}
        for name in BYOK_MODEL_NAMES:
            prefix, _, _ = name.partition(":")
            counts[prefix] = counts.get(prefix, 0) + 1

        self.assertEqual(counts["openai"], 3)
        self.assertEqual(counts["anthropic"], 3)
        # OpenRouter is an open-ended list that gets extended as models are
        # vetted, so only its presence is pinned.
        self.assertGreaterEqual(counts["openrouter"], 1)
        # The DeepSeek entries are commented out for now. The provider stays
        # wired up, so re-enabling them is uncommenting two lines.
        self.assertNotIn("deepseek", counts)
        self.assertIn("deepseek", PROVIDERS)

    def test_every_catalogue_name_resolves(self) -> None:
        for name in BYOK_MODEL_NAMES:
            with self.subTest(name=name):
                prefix, _, _ = name.partition(":")
                spec, model_name = resolve_byok_provider(name)

                self.assertIsInstance(spec, ProviderSpec)
                self.assertIs(spec, PROVIDERS[prefix])
                self.assertNotEqual(model_name, "")
                self.assertTrue(is_byok_model(name))

    def test_free_models_are_not_byok(self) -> None:
        for name in agent_mapper:
            with self.subTest(name=name):
                self.assertFalse(is_byok_model(name))

    def test_unresolvable_names_are_not_byok(self) -> None:
        for name in ("gpt-4o", "nope:gpt-4o", "openai:", ":", ""):
            with self.subTest(name=name):
                self.assertFalse(is_byok_model(name))


class ResolveByokProviderTests(unittest.TestCase):
    def test_provider_and_model_are_separated_without_a_key(self) -> None:
        spec, model_name = resolve_byok_provider("openrouter:gpt-4o")

        self.assertIs(spec.provider, OpenRouterProvider)
        self.assertIs(spec.model, OpenRouterModel)
        self.assertEqual(model_name, "gpt-4o")

    def test_slashes_in_the_model_name_are_kept(self) -> None:
        spec, model_name = resolve_byok_provider(
            "openrouter:meta-llama/llama-3.3-70b-instruct"
        )

        self.assertIs(spec.provider, OpenRouterProvider)
        self.assertEqual(model_name, "meta-llama/llama-3.3-70b-instruct")

    def test_malformed_and_unknown_names_are_rejected(self) -> None:
        for name in (
            "",
            "gpt-4o",
            "openai:",
            ":gpt-4o",
            "nope:gpt-4o",
            "deepseek:deepseek-nope",
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    resolve_byok_provider(name)


class SplitModelNameTests(unittest.TestCase):
    def test_free_names_split_on_the_slash(self) -> None:
        self.assertEqual(
            split_model_name("nvidia/laguna-xs-2.1"), ("nvidia", "laguna-xs-2.1")
        )

    def test_byok_names_split_on_the_colon(self) -> None:
        self.assertEqual(
            split_model_name("openai:gpt-4o-mini"), ("openai", "gpt-4o-mini")
        )

    def test_byok_openrouter_keeps_its_slash_in_the_model(self) -> None:
        self.assertEqual(
            split_model_name("openrouter:qwen/qwen-2.5-72b-instruct"),
            ("openrouter", "qwen/qwen-2.5-72b-instruct"),
        )

    def test_an_unrecognised_name_is_unknown(self) -> None:
        self.assertEqual(split_model_name("junk"), ("unknown", "junk"))


def configured_key(model: object) -> object:
    """The API key a built model's SDK client was constructed with.

    Providers differ: the OpenAI-compatible clients (OpenAI, DeepSeek,
    OpenRouter) expose ``api_key`` directly, while the Google client nests it
    under ``_api_client``.
    """
    client = model.provider.client  # type: ignore[attr-defined]
    if hasattr(client, "api_key"):
        return client.api_key
    return client._api_client.api_key


class BuildAgentTests(unittest.TestCase):
    def test_every_catalogue_name_builds_an_agent(self) -> None:
        for name in BYOK_MODEL_NAMES:
            with self.subTest(name=name):
                self.assertIsInstance(build_agent(name, "test-key"), Agent)

    def test_the_supplied_key_reaches_the_provider_client(self) -> None:
        for name in BYOK_MODEL_NAMES:
            with self.subTest(name=name):
                agent = build_agent(name, "sk-explicit-123")
                # ``Agent.model`` -> provider -> SDK client, as constructed.
                self.assertEqual(configured_key(agent.model), "sk-explicit-123")

    def test_an_environment_key_is_never_fallen_back_to(self) -> None:
        """The key is a parameter, so a host env var must not be picked up."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=False):
            agent = build_agent("openai:gpt-4o-mini", "explicit-key")

        self.assertEqual(configured_key(agent.model), "explicit-key")


class ResolveModelTests(unittest.TestCase):
    def test_free_models_resolve_from_the_directory(self) -> None:
        for name, model in agent_mapper.items():
            with self.subTest(name=name):
                self.assertIs(resolve_model(name), model)

    def test_byok_names_need_a_key_and_use_it(self) -> None:
        model = resolve_model("openai:gpt-4o-mini", "sk-byok")

        self.assertEqual(configured_key(model), "sk-byok")

    def test_a_key_for_a_free_model_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_model("nvidia/laguna-xs-2.1", "sk-unnecessary")

    def test_an_unknown_model_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_model("nope:gpt-4o", None)
