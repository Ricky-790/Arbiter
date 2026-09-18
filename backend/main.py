# import json
# import os

# from dotenv import load_dotenv

# load_dotenv()
# import logfire.db_api

# conn = logfire.db_api.connect(read_token=os.getenv("READ_TOKEN", ""))
# cursor = conn.cursor()
# cursor.execute("""SELECT
#     start_timestamp,
#     duration AS latency_seconds,
#     span_name,
#     trace_id,
#     attributes
# FROM records
# WHERE attributes->>'arbiter.match_id' = 'live-protected-secret'
# ORDER BY start_timestamp ASC;""")
# rows = cursor.fetchall()
# with open("a.json", "w") as f:
#     f.write(json.dumps(rows, indent=2))
#     f.close()
# conn.close()


import os

from dotenv import load_dotenv
from pydantic_ai.agent import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

load_dotenv()


nvidia_provider = OpenAIProvider(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY", ""),
)

settings = ModelSettings(temperature=0.5, thinking="low")
deepseek_v4_flash = OpenAIChatModel(
    model_name="deepseek-ai/deepseek-v4-flash-0731",
    provider=nvidia_provider,
    settings=settings,
)

agent = Agent(deepseek_v4_flash, output_type=str)

result = agent.run_sync("Whats 2+2")
print(result.output)
