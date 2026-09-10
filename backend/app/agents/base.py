from __future__ import annotations

import asyncio
import inspect
import json
from collections import deque
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

# from tenacity import retry, stop_after_attempt, wait_exponential
from app.logger import get_logger

from .agents_directory import agent_mapper
from .tokens import (
    HIDDEN_OUTPUT_PLACEHOLDER,
    count_tokens,
    lower_token_limit,
)
from .tools.models import ToolCall, ToolResult

if TYPE_CHECKING:
    from .tools.registry import ToolRegistry

logger = get_logger()


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
        # Ordered (ToolCall, ToolResult) pairs; rendered as JSON in prompts so
        # the LLM sees both its prior reasoning and each result. Never shared
        # between agent instances.
        self._observations: list[tuple[ToolCall, ToolResult]] = []
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
            prompt += "\nRecent tool calls and results (JSON):\n" + "\n".join(
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

    async def observe_result(self, call: ToolCall, result: ToolResult) -> None:
        # Store copies: later hiding redacts stored outputs in place and must
        # never mutate the result the engine recorded.
        self._observations.append(
            (call.model_copy(deep=True), result.model_copy(deep=True))
        )
        self._hide_older_observations()

    def _hide_older_observations(self) -> None:
        """Hide the ``output`` field of older over-budget results in place.

        Called right after a new pair is observed, so the just-observed
        output stays full for one turn. Only the oversized ``output`` field
        is replaced; ``success``, ``error``, ``exit_code``, ``notice`` (and
        the paired reason) are kept as-is.
        """
        if len(self._observations) <= 1:
            return
        limit = lower_token_limit()
        for i in range(len(self._observations) - 1):
            _, stored = self._observations[i]
            if count_tokens(stored.output or "") > limit:
                self._observations[i] = (
                    self._observations[i][0],
                    stored.model_copy(
                        update={"output": HIDDEN_OUTPUT_PLACEHOLDER}
                    ),
                )

    def _format_recent_observations(self) -> list[str]:
        """Render the last 5 (call, result) pairs as JSON: most recent full.

        Defensive pass for the case where limits changed at runtime or
        history predates hiding; normally ``_hide_older_observations`` has
        already hidden older large outputs in place.
        """
        limit = lower_token_limit()
        recent = self._observations[-5:]
        formatted: list[str] = []
        for j, (call, result) in enumerate(recent):
            is_most_recent = j == len(recent) - 1
            if not is_most_recent and count_tokens(result.output or "") > limit:
                result = result.model_copy(
                    update={"output": HIDDEN_OUTPUT_PLACEHOLDER}
                )
            formatted.append(
                json.dumps(
                    {
                        "tool_call": call.model_dump(),
                        "tool_result": result.model_dump(
                            exclude_none=True, exclude={"metadata"}
                        ),
                    },
                    ensure_ascii=False,
                )
            )
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
        return ToolCall(name=call.name, arguments=coerced, reason=call.reason)

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
