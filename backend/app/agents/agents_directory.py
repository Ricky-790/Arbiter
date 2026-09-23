"""The model directory: free models and BYOK model construction"""

import os
from typing import NamedTuple, get_args

from dotenv import load_dotenv
from pydantic_ai import ModelSettings
from pydantic_ai.agent import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers import Provider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.deepseek import DeepSeekModelName, DeepSeekProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

load_dotenv()

# Providers
nvidia_provider = OpenAIProvider(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY", ""),
)
token_router_provider = OpenAIProvider(
    base_url="https://api.tokenrouter.com/v1", api_key=os.getenv("TOKENROUTER_API_KEY")
)
# groq_provider = GroqProvider()
openrouter_provider = OpenRouterProvider()
google_provider = GoogleProvider(api_key=os.getenv("GOOGLE_API_KEY", ""))

# Models
laguna = OpenAIChatModel(model_name="poolside/laguna-xs-2.1", provider=nvidia_provider)
gemini_3_6 = GoogleModel(model_name="gemini-3.6-flash", provider=google_provider)
gemini_3_1 = GoogleModel(model_name="gemini-3.1-flash-lite", provider=google_provider)
liquid_ai_lfm = OpenRouterModel(
    model_name="liquid/lfm-2.5-2.6b:free", provider=openrouter_provider
)
minimax_m3 = OpenAIChatModel(
    model_name="minimaxai/minimax-m3", provider=nvidia_provider
)
ling_3_flash = OpenRouterModel(
    model_name="inclusionai/ling-3.0-flash-vl:free", provider=openrouter_provider
)
settings = ModelSettings(temperature=0.5, thinking="low")
glm_5_3 = OpenAIChatModel(model_name="z-ai/glm-5.3-flash", provider=nvidia_provider)
deepseek_v4_flash = OpenAIChatModel(
    model_name="deepseek-ai/deepseek-v4-flash-0731",
    provider=nvidia_provider,
    settings=settings,
)
agent_mapper = {
    "nvidia/laguna-xs-2.1": laguna,
    # "google/gemini-3.6-flash": gemini_3_6,
    # "openrouter/lfm-2.5-2.6b": liquid_ai_lfm,
    # "nvidia/minimax-m3": minimax_m3,
    # "openrouter/ling-3.0-flash": ling_3_flash,
    "nvidia/glm-5.3": glm_5_3,
    # "google/gemini-3.1-flash-lite": gemini_3_1,
    "nvidia/deepseek-v4-flash-0731": deepseek_v4_flash,
}


def split_model_name(model_name: str) -> tuple[str, str]:
    """Split a model key into ``(provider, model)``.

    The ``matches`` table stores the provider and model in separate columns,
    while the API and queue carry one combined key: ``provider/model`` for a
    free model, ``provider:model`` for a BYOK one.
    """
    if ":" in model_name:
        provider, _, byok_model = model_name.partition(":")
        if provider in PROVIDERS and byok_model:
            return provider, byok_model
    provider, separator, model = model_name.partition("/")
    if not separator:
        return "unknown", model_name
    return provider, model


class ProviderSpec(NamedTuple):
    """The pydantic-ai classes that serve one BYOK ``provider:`` prefix."""

    provider: type[Provider]
    model: type[Model]


#: BYOK prefix -> the classes that build a model for it. DeepSeek speaks the
#: OpenAI chat API, so it reuses ``OpenAIChatModel`` with its own provider.
PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(OpenAIProvider, OpenAIChatModel),
    "anthropic": ProviderSpec(AnthropicProvider, AnthropicModel),
    "deepseek": ProviderSpec(DeepSeekProvider, OpenAIChatModel),
    "openrouter": ProviderSpec(OpenRouterProvider, OpenRouterModel),
    "google": ProviderSpec(GoogleProvider, GoogleModel),
}

#: BYOK models, named as ``provider:model``. The prefix must be a key of
#: :data:`PROVIDERS`; each needs a caller-supplied API key.
BYOK_MODEL_NAMES: list[str] = [
    # OpenAI
    "openai:gpt-4o-mini",
    "openai:gpt-4o",
    "openai:gpt-4.1-mini",
    # Anthropic
    "anthropic:claude-3-5-haiku-latest",
    "anthropic:claude-3-5-sonnet-latest",
    "anthropic:claude-3-7-sonnet-latest",
    # DeepSeek
    # "deepseek:deepseek-v4-flash",
    # "deepseek:deepseek-v4-pro",
    # OpenRouter
    "openrouter:google/gemini-2.0-flash-001",
    "openrouter:meta-llama/llama-3.3-70b-instruct",
    "openrouter:qwen/qwen-2.5-72b-instruct",
    "openrouter:inclusionai/ling-3.0-flash-sante:free",
    "openrouter:inclusionai/ling-3.0-flash-fin:free",
    "openrouter:qwen/qwen3.8-27b:free",
    "openrouter:free",
    # Google
    "google:gemini-3.1-flash-lite",
]


def resolve_byok_provider(full_model_name: str) -> tuple[ProviderSpec, str]:
    """Split ``openai:gpt-4o-mini`` into its provider spec and model name.

    Credentials play no part: the prefix is mapped onto provider/model classes
    only, so the model can be built later with whatever key the caller has. The
    model name keeps any slashes OpenRouter needs
    (``openrouter:meta-llama/llama-3.3-70b-instruct``).

    Raises:
        ValueError: if the name is not ``provider:model`` or the prefix is
            unknown.
    """
    prefix, separator, model_name = full_model_name.partition(":")
    if not separator or not prefix or not model_name:
        raise ValueError(f"Expected a 'provider:model' name, got {full_model_name!r}")
    try:
        spec = PROVIDERS[prefix]
    except KeyError:
        known = ", ".join(sorted(PROVIDERS))
        raise ValueError(
            f"Unknown provider {prefix!r} in {full_model_name!r}; known: {known}"
        ) from None
    if prefix == "deepseek" and model_name not in get_args(DeepSeekModelName):
        known = ", ".join(get_args(DeepSeekModelName))
        raise ValueError(f"Unknown DeepSeek model {model_name!r}; known: {known}")
    return spec, model_name


def is_byok_model(model_name: str) -> bool:
    """Whether ``model_name`` is a BYOK model (and so needs a caller's key)."""
    try:
        resolve_byok_provider(model_name)
    except ValueError:
        return False
    return model_name not in agent_mapper


def build_model(full_model_name: str, api_key: str) -> Model:
    """Build a BYOK ``Model`` for ``"provider:model"`` with ``api_key``.

    The key is a parameter rather than an environment lookup, so the caller
    decides where credentials come from. Nothing is sent to the provider here:
    only the model client is constructed.
    """
    spec, model_name = resolve_byok_provider(full_model_name)
    return spec.model(model_name=model_name, provider=spec.provider(api_key=api_key))


def build_agent(full_model_name: str, api_key: str) -> Agent:
    """Build an ``Agent`` for a BYOK ``"provider:model"`` and key."""
    return Agent(build_model(full_model_name, api_key))


def resolve_model(model_name: str, api_key: str | None = None) -> Model:
    """Return the ``Model`` for a free or BYOK name.

    Free models come from :data:`agent_mapper` and take no key. A BYOK name is
    built on the spot from the caller's key; anything else is rejected rather
    than silently falling back to a different model.
    """
    free_model = agent_mapper.get(model_name)
    if free_model is not None:
        if api_key:
            raise ValueError(
                f"Model {model_name!r} is a free model and takes no API key"
            )
        return free_model
    if not api_key:
        raise ValueError(
            f"Unknown model {model_name!r}. Free models: "
            f"{', '.join(sorted(agent_mapper))}. BYOK names are "
            f"'provider:model' with one of these prefixes: "
            f"{', '.join(sorted(PROVIDERS))}"
        )
    return build_model(model_name, api_key)
