import os

from dotenv import load_dotenv
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

# groq_provider = GroqProvider()
openrouter_provider = OpenRouterProvider()
google_provider = GoogleProvider(api_key=os.getenv("GOOGLE_API_KEY", ""))

# Models
laguna = OpenAIChatModel(model_name="poolside/laguna-xs-2.1", provider=nvidia_provider)
gemini_3_1 = GoogleModel(model_name="gemini-3.1-flash-lite", provider=google_provider)
liquid_ai_lfm = OpenRouterModel(
    model_name="liquid/lfm-2.5-2.6b:free", provider=openrouter_provider
)
minimax_m3 = OpenAIChatModel(
    model_name="minimaxai/minimax-m3", provider=nvidia_provider
)

agent_mapper = {
    "laguna-xs-2.1": laguna,
    "gemini-3.1-flash-lite": gemini_3_1,
    "lfm-2.5-2.6b": liquid_ai_lfm,
    "minimax-m3": minimax_m3,
}
