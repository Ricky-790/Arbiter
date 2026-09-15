from __future__ import annotations

import asyncio
import inspect
import json
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    RunContext,
    ToolDefinition,
)
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.toolsets.external import ExternalToolset

# from tenacity import retry, stop_after_attempt, wait_exponential
from app.logger import get_logger

from .agents_directory import agent_mapper
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


def _function_signature_to_json_schema(tool: Any) -> dict[str, Any]:
    """Build a minimal JSON schema for a BaseTool's execute() method."""
    sig = inspect.signature(tool.execute)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in {"self", "context"}:
            continue
        schema: dict[str, Any] = {}
        annotation = param.annotation
        if annotation is not inspect.Parameter.empty:
            if annotation is str:
                schema["type"] = "string"
            elif annotation is int:
                schema["type"] = "integer"
            elif annotation is bool:
                schema["type"] = "boolean"
            elif annotation is float:
                schema["type"] = "number"
            else:
                origin = get_origin(annotation)
                if origin is Union or (hasattr(origin, "__origin__") and origin.__origin__ is Union):  # type: ignore[attr-defined]
                    members = [m for m in get_args(annotation) if m is not type(None)]
                    types: list[str] = []
                    for m in members:
                        if m is str:
                            types.append("string")
                        elif m is int:
                            types.append("integer")
                        else:
                            types.append("object")
                    if len(types) == 1:
                        schema["type"] = types[0]
                    else:
                        schema["type"] = types
                    if type(None) in get_args(annotation):
                        schema["nullable"] = True
                else:
                    schema["type"] = "object"
        else:
            schema["type"] = "string"
        properties[name] = schema
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _build_tool_definitions(
    registry: ToolRegistry, allowed_tools: set[str]
) -> list[ToolDefinition]:
    tool_defs: list[ToolDefinition] = []
    for name in allowed_tools:
        try:
            tool = registry.get(name)
        except KeyError:
            continue
        tool_defs.append(
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=_function_signature_to_json_schema(tool),
                kind="external",
            )
        )
    return tool_defs


class ToolChoosingAgent:
    """An LLM agent that uses Pydantic AI native deferred tool calling.

    The model is given the list of allowed tools as external/deferred tools.
    A ``HandleDeferredToolCalls`` capability resolves each request inline
    through an engine-bound executor, so one native ``agent.run()`` drives
    the whole turn -- no manual request/resume loop.
    """

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
        self._scripted_calls = deque(scripted_calls or ())
        self._scripted_mode = scripted_calls is not None

        if registry is None:
            from .tools.registry import build_default_registry

            registry = build_default_registry()
        self._registry = registry

        tool_defs = _build_tool_definitions(registry, allowed_tools)

        # Resolved per deferred request by the bound engine executor; None
        # until the engine binds it (standalone/scripted use has no executor).
        self._tool_executor: (
            Callable[[str, dict[str, Any]], Awaitable[Any]] | None
        ) = None

        self._agent = Agent(
            model,
            output_type=[str, DeferredToolRequests],
            instructions=instructions,
            toolsets=[ExternalToolset(tool_defs)],
            capabilities=[
                HandleDeferredToolCalls(handler=self._handle_deferred_tools)
            ],
        )

        self._message_history: list[Any] | None = None

        # Ordered (ToolCall, ToolResult) pairs; rendered as JSON in prompts so
        # the LLM sees both its prior reasoning and each results. Never shared
        # between agent instances.
        self._observations: list[tuple[ToolCall, ToolResult]] = []

    def bind_tool_executor(
        self,
        executor: Callable[[str, dict[str, Any]], Awaitable[Any]],
    ) -> None:
        """Bind the engine's authoritative tool executor for this match."""
        self._tool_executor = executor

    async def _handle_deferred_tools(
        self, ctx: RunContext, requests: DeferredToolRequests
    ) -> DeferredToolResults | None:
        """Native inline resolver: run each deferred call via the engine."""
        if self._tool_executor is None:
            return None
        calls: dict[str, Any] = {}
        for call in requests.calls:
            try:
                calls[call.tool_call_id] = await self._tool_executor(
                    call.tool_name, call.args_as_dict()
                )
            except Exception as error:
                logger.error(f"Deferred tool executor failed: {error}")
                calls[call.tool_call_id] = {
                    "success": False,
                    "error": f"Tool execution failed: {error}",
                }
        return requests.build_results(calls=calls)

    async def run_turn(self, scratchpad: str = "") -> str | None:
        """Run one native agent turn, resolving tools inline via the handler.

        Returns the model's final text output, or None when the turn
        produced nothing usable (scripted mode, rate limits exhausted,
        provider errors). Message history carries over across turns.
        """
        if self._scripted_calls:
            call = self._validate(self._scripted_calls.popleft())
            if self._tool_executor is not None:
                await self._tool_executor(call.name, dict(call.arguments))
            return None
        if self._scripted_mode:
            return None

        prompt = "Choose exactly one next tool call."
        if self.objective:
            prompt += f"\nCurrent match objective: {self.objective}"
        prompt += f"\nYour scratchpad:\n<scratchpad>{scratchpad}</scratchpad>"
        if self._observations:
            prompt += "\nRecent tool calls and results (JSON):\n" + "\n".join(
                self._format_recent_observations()
            )
        for _ in range(3):
            try:
                result = await self._agent.run(
                    prompt, message_history=self._message_history
                )
                self._message_history = result.all_messages()
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
                    return None
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return None
            if isinstance(result.output, str):
                return result.output
            logger.error(
                f"Unexpected agent output type: {type(result.output).__name__}"
            )
            return None
        logger.critical("Max retries exceeded for tool call generation.")
        return None

    async def observe_result(self, call: ToolCall, result: ToolResult) -> None:
        # Store copies so later callers can never mutate the recorded result.
        self._observations.append(
            (call.model_copy(deep=True), result.model_copy(deep=True))
        )

    def _format_recent_observations(self) -> list[str]:
        """Render the last 5 (call, result) pairs as JSON, outputs intact."""
        formatted: list[str] = []
        for call, result in self._observations[-5:]:
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
