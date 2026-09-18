import os

from dotenv import load_dotenv
from pydantic_ai import ModelSettings
from pydantic_ai.agent import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider
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
    "laguna-xs-2.1": laguna,
    "gemini-3.6-flash": gemini_3_6,
    "lfm-2.5-2.6b": liquid_ai_lfm,
    "minimax-m3": minimax_m3,
    "ling-3.0-flash": ling_3_flash,
    "glm-5.3": glm_5_3,
    "gemini-3.1-flash-lite": gemini_3_1,
    "deepseek-v4-flash-0731": deepseek_v4_flash,
}

# agent = Agent(gemini_3_6, output_type=str)
# result = agent.run_sync("Whats 2+2")
# print(result.output)
