from __future__ import annotations

import asyncio
import inspect
import os
from collections import deque
from collections.abc import Iterable
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

# from tenacity import retry, stop_after_attempt, wait_exponential
from app.logger import get_logger

from .agents_directory import agent_mapper
from .tools.models import ToolCall, ToolResult

if TYPE_CHECKING:
    from .tools.registry import ToolRegistry

logger = get_logger()

LONG_OUTPUT_NOTICE = (
    "Output very long, will be truncated / replaced next turn. "
    "Please use write to scratchpad tool to note any important observations."
)

HIDDEN_OUTPUT_PLACEHOLDER = (
    "[Long Output hidden, please refer to scratchpad for important information]"
)


def _max_output_tokens() -> int:
    """Token budget for a single tool output, read from .env (`MAX_TOKENS`)."""
    try:
        return int(os.getenv("MAX_TOKENS", "4000"))
    except (TypeError, ValueError):
        return 4000


@lru_cache(maxsize=1)
def _get_encoding():  # type: ignore[no-untyped-def]
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _count_tokens(text: str) -> int:
    enc = _get_encoding()
    if enc is None:
        # Fallback heuristic (~4 chars/token) when tiktoken is unavailable.
        return max(1, len(text) // 4) if text else 0
    return len(enc.encode(text))


try:
    import types as _stdlib_types

    _UNION_ORIGINS = (Union, _stdlib_types.UnionType)
except AttributeError:  # Python < 3.10 has no types.UnionType
    _UNION_ORIGINS = (Union,)


def _type_name(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return "Any"
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


def _coerce_argument(
    *, tool_name: str, arg_name: str, value: Any, annotation: Any
) -> Any:
    """Leniently coerce one argument value to its annotated type."""

    def err(expected: str) -> ValueError:
        return ValueError(
            f"Tool {tool_name!r} argument {arg_name!r} must be "
            f"{expected}, got {value!r}."
        )

    if annotation is inspect.Parameter.empty or annotation is Any:
        return value
    if get_origin(annotation) in _UNION_ORIGINS:
        members = get_args(annotation)
        if value is None:
            if type(None) in members:
                return None
            raise err(" / ".join(_type_name(m) for m in members))
        last_error: ValueError | None = None
        for member in members:
            if member is type(None):
                continue
            try:
                return _coerce_argument(
                    tool_name=tool_name,
                    arg_name=arg_name,
                    value=value,
                    annotation=member,
                )
            except ValueError as exc:
                last_error = exc
        raise last_error if last_error is not None else err("a valid value")
    if isinstance(annotation, type):
        if isinstance(value, annotation):
            if annotation is int and isinstance(value, bool):
                raise err("int")
            return value
        if annotation is int and not isinstance(value, bool):
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value.strip())
                except ValueError:
                    pass
            raise err("int")
        if annotation is str and isinstance(value, (int, float)) and not isinstance(
            value, bool
        ):
            return str(value)
        raise err(_type_name(annotation))
    return value


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
        registry: ToolRegistry | None = None,
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
        if registry is None:
            from .tools.registry import build_default_registry

            registry = build_default_registry()
        self._registry = registry
        self._observations: list[str] = []
        self._scripted_calls = deque(scripted_calls or ())
        self._scripted_mode = scripted_calls is not None

    # @retry(wait=wait_exponential(min=1, max=60), stop=stop_after_attempt(3))
    async def next_tool_call(self, scratchpad: str = "") -> ToolCall:

        if self._scripted_calls:
            return self._validate(self._scripted_calls.popleft())
        if self._scripted_mode:
            return ToolCall(name="pass")

        retries = 3

        prompt = "Choose exactly one next tool call."

        if self.objective:
            prompt += f"\nCurrent match objective: {self.objective}"
        prompt += f"\nYour scratchpad:\n<scratchpad>{scratchpad}</scratchpad>"
        if self._observations:
            prompt += "\nRecent tool results:\n" + "\n".join(
                self._format_recent_observations()
            )
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
            continue
        logger.critical("Max retries exceeded for tool call generation.")
        return ToolCall(name="pass")

    async def observe_result(self, result: ToolResult) -> None:
        summary = result.output if result.success else f"ERROR: {result.error}"
        summary = summary or ""
        limit = _max_output_tokens()
        token_count = _count_tokens(summary)
        if token_count > limit:
            # Full output is kept for exactly this turn: it becomes the most
            # recent observation and is sent verbatim on the next prompt,
            # plus a notice so the agent persists anything important.
            summary = (
                f"{summary}\n\n{LONG_OUTPUT_NOTICE} "
                f"(output was ~{token_count} tokens, limit is {limit} tokens.)"
            )
            logger.info(
                f"Large tool output ({token_count} tokens > {limit}): "
                "keeping full output for this turn only."
            )
        self._observations.append(summary)
        self._truncate_older_observations()

    def _truncate_older_observations(self) -> None:
        """Replace every observation except the most recent if over budget.

        Called right after a new result is observed, so the just-observed
        output stays full for one turn and older large outputs are hidden.
        """
        if len(self._observations) <= 1:
            return
        limit = _max_output_tokens()
        for i in range(len(self._observations) - 1):
            if _count_tokens(self._observations[i]) > limit:
                self._observations[i] = HIDDEN_OUTPUT_PLACEHOLDER

    def _format_recent_observations(self) -> list[str]:
        """Render the last 5 observations: most recent full, older hidden.

        Defensive pass for the case where MAX_TOKENS changed at runtime or
        history predates hiding; normally _truncate_older_observations
        has already replaced older large entries in place.
        """
        limit = _max_output_tokens()
        recent = self._observations[-5:]
        formatted: list[str] = []
        for j, text in enumerate(recent):
            is_most_recent = j == len(recent) - 1
            if not is_most_recent and _count_tokens(text) > limit:
                formatted.append(HIDDEN_OUTPUT_PLACEHOLDER)
            else:
                formatted.append(text)
        return formatted

    def _validate(self, call: ToolCall) -> ToolCall:
        if call.name not in self.allowed_tools:
            raise ValueError(f"Agent selected unavailable tool {call.name!r}")
        try:
            tool = self._registry.get(call.name)
        except KeyError as error:
            raise ValueError(f"Unknown tool: {call.name!r}") from error
        params = {
            name: param
            for name, param in inspect.signature(tool.execute).parameters.items()
            if name not in {"self", "context"}
        }
        arguments = dict(call.arguments or {})
        try:
            bound = inspect.Signature(parameters=list(params.values())).bind(
                **arguments
            )
        except TypeError as error:
            raise ValueError(
                f"Tool {call.name!r} called with invalid arguments: {error}. "
                f"Expected arguments: {self._expected_args_hint(params)}."
            ) from error
        coerced = {
            name: _coerce_argument(
                tool_name=call.name,
                arg_name=name,
                value=value,
                annotation=params[name].annotation,
            )
            for name, value in bound.arguments.items()
        }
        return ToolCall(name=call.name, arguments=coerced)

    @staticmethod
    def _expected_args_hint(params: dict[str, inspect.Parameter]) -> str:
        parts = []
        for name, param in params.items():
            required = (
                "required"
                if param.default is inspect.Parameter.empty
                else "optional"
            )
            parts.append(f"{name} ({_type_name(param.annotation)}, {required})")
        return ", ".join(parts) if parts else "no arguments"
