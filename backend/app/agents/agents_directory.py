"""The model directory: the providers Arbiter can run, and the models they serve.

Every agent model is BYOK. Arbiter holds no provider credentials for agent
models: each side of a match supplies its own API key, the API stores it briefly
(``app.secrets``), and the worker redeems it to build that side's model.

:data:`PROVIDER_MODELS` is a set of *suggestions* for the picker, not a
whitelist. The picker also accepts a pasted model name, so the authoritative
check is :func:`check_model_exists`, which asks the provider itself what it
serves using the caller's key. Only OpenRouter publishes a keyless model list,
which is why the curated names exist at all: without them the picker would open
empty for the other three.
"""

from __future__ import annotations

import hashlib
import time
from typing import NamedTuple

from pydantic_ai.agent import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers import Provider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider


class ProviderSpec(NamedTuple):
    """The pydantic-ai classes that serve one provider."""

    provider: type[Provider]
    model: type[Model]


#: Provider name -> the classes that build a model for it.
PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(OpenAIProvider, OpenAIChatModel),
    "anthropic": ProviderSpec(AnthropicProvider, AnthropicModel),
    "google": ProviderSpec(GoogleProvider, GoogleModel),
    "openrouter": ProviderSpec(OpenRouterProvider, OpenRouterModel),
}

#: Provider name -> the models it offers, in the order the UI should list them.
#: OpenRouter entries keep their ``vendor/model`` slash; the provider prefix is
#: carried separately, so a name is only ever ``provider:model`` when joined.
PROVIDER_MODELS: dict[str, list[str]] = {
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "o3",
        "o4-mini",
    ],
    "anthropic": [
        "claude-3-5-haiku-latest",
        "claude-3-5-sonnet-latest",
        "claude-3-7-sonnet-latest",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
    ],
    "google": [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-3.1-flash-lite",
    ],
    "openrouter": [
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "anthropic/claude-sonnet-4.6",
        "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen-2.5-72b-instruct",
        "mistralai/mistral-large",
    ],
}

#: OpenAI-compatible endpoints, which differ only by base URL. OpenRouter speaks
#: the OpenAI chat API, so both are listed with the same SDK.
_OPENAI_COMPATIBLE_BASE_URLS: dict[str, str | None] = {
    "openai": None,
    "openrouter": "https://openrouter.ai/api/v1",
}

#: How long a successful check is trusted. The UI verifies a pasted name as the
#: operator types and start-match verifies again before queueing; without this
#: the same pair would be looked up twice within seconds.
_CHECK_TTL_SECONDS = 300.0

#: How long to wait for a provider's model list before calling the check
#: unavailable. Long enough for a slow list, short enough not to stall a match.
_CHECK_TIMEOUT_SECONDS = 15.0

#: Successful checks only. Keyed by ``(provider, model, key fingerprint)``: the
#: fingerprint is a digest, so no API key is retained here.
_check_cache: dict[tuple[str, str, str], float] = {}


class ModelCheckError(Exception):
    """A model name could not be confirmed with its provider.

    ``reason`` is one of ``not_found`` (the provider answered and does not serve
    it), ``key_rejected`` (the provider refused the credential) or
    ``unreachable`` (the list could not be read at all).
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def models_for(provider: str) -> list[str]:
    """The suggested models under ``provider``, or an empty list if unknown."""
    return list(PROVIDER_MODELS.get(provider, ()))


def is_curated_model(provider: str, model: str) -> bool:
    """Whether ``(provider, model)`` is one of the picker's suggestions."""
    return model in PROVIDER_MODELS.get(provider, ())


def is_known_provider(provider: str) -> bool:
    """Whether Arbiter can drive ``provider`` at all."""
    return provider in PROVIDERS


def join_model_name(provider: str, model: str) -> str | None:
    """Combine the separate ``provider`` and ``model`` into ``provider:model``.

    The inverse of storing the pair in the ``matches`` columns, and the form the
    agent runtime resolves. Returns ``None`` when the provider is not one
    Arbiter can drive or the model is blank.

    The model name is deliberately *not* checked against :data:`PROVIDER_MODELS`:
    that list is only a set of suggestions, and the picker accepts a pasted name
    too. The authoritative check is :func:`check_model_exists`, which asks the
    provider. A name that passes here can still be rejected there.
    """
    if not is_known_provider(provider) or not model:
        return None
    return f"{provider}:{model}"


def resolve_provider(full_model_name: str) -> tuple[ProviderSpec, str]:
    """Split ``openai:gpt-4o-mini`` into its provider spec and model name.

    Credentials play no part: the prefix is mapped onto provider/model classes
    only, so the model can be built later with whatever key the caller has. The
    model name keeps any slashes OpenRouter needs
    (``openrouter:meta-llama/llama-3.3-70b-instruct``).

    Raises:
        ValueError: if the name is not ``provider:model`` or the provider is not
            one Arbiter can drive. The model itself is not validated here; see
            :func:`check_model_exists`.
    """
    provider_name, separator, model_name = full_model_name.partition(":")
    if not separator or not provider_name or not model_name:
        raise ValueError(f"Expected a 'provider:model' name, got {full_model_name!r}")
    try:
        spec = PROVIDERS[provider_name]
    except KeyError:
        known = ", ".join(sorted(PROVIDERS))
        raise ValueError(
            f"Unknown provider {provider_name!r} in {full_model_name!r}; known: {known}"
        ) from None
    return spec, model_name


def build_model(full_model_name: str, api_key: str) -> Model:
    """Build a ``Model`` for ``"provider:model"`` with ``api_key``.

    The key is a parameter rather than an environment lookup, so the caller
    decides where credentials come from. Nothing is sent to the provider here:
    only the model client is constructed.
    """
    spec, model_name = resolve_provider(full_model_name)
    return spec.model(model_name=model_name, provider=spec.provider(api_key=api_key))


def build_agent(full_model_name: str, api_key: str) -> Agent:
    """Build an ``Agent`` for ``"provider:model"`` and the caller's key."""
    return Agent(build_model(full_model_name, api_key))


def resolve_model(model_name: str, api_key: str | None = None) -> Model:
    """Return the ``Model`` for a ``"provider:model"`` name and the caller's key.

    Every model is BYOK, so a missing key is an error rather than a silent
    fallback: an agent must never be built without the credentials its side
    supplied. An unknown provider is rejected too, instead of quietly resolving
    to some other model.
    """
    if not api_key:
        raise ValueError(f"Model {model_name!r} needs a provider API key")
    return build_model(model_name, api_key)


def _key_fingerprint(api_key: str) -> str:
    """A short digest used as a cache key, so no API key is ever retained."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


async def _list_openai_compatible_models(provider: str, api_key: str) -> set[str]:
    """Model ids from an OpenAI-compatible ``/models`` endpoint."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=_OPENAI_COMPATIBLE_BASE_URLS[provider],
        timeout=_CHECK_TIMEOUT_SECONDS,
    )
    return {model.id async for model in await client.models.list()}


async def _list_anthropic_models(api_key: str) -> set[str]:
    """Model ids from Anthropic's ``/v1/models``."""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key, timeout=_CHECK_TIMEOUT_SECONDS)
    return {model.id async for model in await client.models.list()}


async def _list_google_models(api_key: str) -> set[str]:
    """Model ids from Google's model list.

    Google reports names as ``models/gemini-2.5-flash``, so the prefix is
    stripped to match the name an operator pastes.
    """
    from google import genai

    client = genai.Client(api_key=api_key)
    names: set[str] = set()
    async for model in await client.aio.models.list():
        if model.name:
            names.add(model.name.removeprefix("models/"))
    return names


#: Provider -> the call that lists what its endpoint currently serves.
_MODEL_LISTERS: dict[str, object] = {
    "openai": lambda key: _list_openai_compatible_models("openai", key),
    "openrouter": lambda key: _list_openai_compatible_models("openrouter", key),
    "anthropic": _list_anthropic_models,
    "google": _list_google_models,
}


def _is_auth_failure(error: BaseException) -> bool:
    """Whether a provider error means the credential was refused.

    Class names are checked as well as status codes because the three SDKs
    disagree on both. Deliberately does not inspect the message: a provider's
    error text can echo the request URL, which for some SDKs carries the key.
    """
    if type(error).__name__ in {"AuthenticationError", "PermissionDeniedError"}:
        return True
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    return status in (401, 403)


async def check_model_exists(provider: str, model: str, api_key: str) -> None:
    """Confirm the provider actually serves ``model`` for ``api_key``.

    This is what stops a mistyped or pasted-wrong name from being queued: the
    worker takes a sandbox before its first model call, so a name that only
    fails at generation time would occupy a scarce sandbox to produce nothing.

    Calls are made server-side with the caller's key. The browsers cannot do
    this themselves: only OpenRouter publishes a CORS-friendly keyless list, and
    sending the other providers' keys from the page would leak them.

    Raises:
        ModelCheckError: with ``reason`` ``not_found``, ``key_rejected`` or
            ``unreachable``. Callers treat all three as "not verified", but the
            distinction is what lets the UI say which.
    """
    lister = _MODEL_LISTERS.get(provider)
    if lister is None:
        raise ModelCheckError("not_found", f"Unknown provider {provider!r}")
    if not model:
        raise ModelCheckError("not_found", "No model name was given")

    cache_key = (provider, model, _key_fingerprint(api_key))
    expires_at = _check_cache.get(cache_key)
    if expires_at is not None and expires_at > time.monotonic():
        return

    try:
        available = await lister(api_key)  # type: ignore[operator]
    except Exception as error:
        # The provider's own text is never surfaced: it can include the request
        # URL, and for some SDKs the key travels in that URL.
        if _is_auth_failure(error):
            raise ModelCheckError(
                "key_rejected", f"{provider} rejected this API key"
            ) from error
        raise ModelCheckError(
            "unreachable", f"Could not reach {provider} to verify the model"
        ) from error

    if model not in available:
        raise ModelCheckError(
            "not_found", f"{provider} does not offer a model named {model!r}"
        )

    _prune_check_cache()
    _check_cache[cache_key] = time.monotonic() + _CHECK_TTL_SECONDS


def _prune_check_cache() -> None:
    """Drop expired entries so a long-lived worker's cache cannot grow forever.

    Expiry is only noticed when the same key is looked up again, so without this
    every distinct model anyone ever checked would be retained for the life of
    the process.
    """
    now = time.monotonic()
    for key in [key for key, expiry in _check_cache.items() if expiry <= now]:
        del _check_cache[key]
