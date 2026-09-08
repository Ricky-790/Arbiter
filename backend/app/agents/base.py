import asyncio
from collections import deque
from collections.abc import Iterable

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

# from tenacity import retry, stop_after_attempt, wait_exponential
from app.logger import get_logger

from .agents_directory import agent_mapper
from .tools.models import ToolCall, ToolResult

logger = get_logger()


class ToolChoosingAgent:
    """An LLM agent that returns a validated structured tool request."""

    def __init__(
        self,
        *,
        model_name: str,
        instructions: str,
        allowed_tools: set[str],
        objective: str | None = None,
        scripted_calls: Iterable[ToolCall] | None = None,
    ) -> None:
        try:
            model = agent_mapper[model_name]
        except KeyError as error:
            supported = ", ".join(sorted(agent_mapper))
            raise ValueError(
                f"Unknown agent model {model_name!r}; choose one of {supported}"
            ) from error
        self.allowed_tools = allowed_tools
        self.objective = objective
        self._agent = Agent(model, output_type=ToolCall, instructions=instructions)
        self._observations: list[str] = []
        self._scripted_calls = deque(scripted_calls or ())
        self._scripted_mode = scripted_calls is not None

    # @retry(wait=wait_exponential(min=1, max=60), stop=stop_after_attempt(3))
    async def next_tool_call(self) -> ToolCall:

        if self._scripted_calls:
            return self._validate(self._scripted_calls.popleft())
        if self._scripted_mode:
            return ToolCall(name="pass")

        retries = 3

        prompt = "Choose exactly one next tool call."

        if self.objective:
            prompt += f"\nCurrent match objective: {self.objective}"
        if self._observations:
            prompt += "\nRecent tool results:\n" + "\n".join(self._observations[-5:])
        current_prompt = prompt
        message_history = None
        for _ in range(retries):
            try:
                result = await self._agent.run(
                    current_prompt, message_history=message_history
                )
                message_history = result.all_messages()
            except ModelHTTPError as e:
                if e.status_code == 429:
                    logger.critical(f"Model rate limit exceeded: {e}")
                    raw_wait = e.headers.get("retry-after", 30) if e.headers else 30
                    try:
                        sleep_time = float(raw_wait)
                    except (ValueError, TypeError):
                        sleep_time = 30.0
                    await asyncio.sleep(sleep_time)
                    continue
                else:
                    logger.error(f"Model HTTP error: {e}")
                    return ToolCall(name="pass")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return ToolCall(name="pass")
            try:
                return self._validate(result.output)
            except ValueError as e:
                logger.error(f"Invalid tool call: {e}")
                current_prompt = f"ERROR: {e}. Please choose a valid tool."
                message_history = result.all_messages()
            return ToolCall(name="pass")
        logger.critical("Max retries exceeded for tool call generation.")
        return ToolCall(name="pass")

    async def observe_result(self, result: ToolResult) -> None:
        summary = result.output if result.success else f"ERROR: {result.error}"
        self._observations.append(summary[:2_000])

    def _validate(self, call: ToolCall) -> ToolCall:
        if call.name not in self.allowed_tools:
            raise ValueError(f"Agent selected unavailable tool {call.name!r}")
        return call
