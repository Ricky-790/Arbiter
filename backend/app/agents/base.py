from __future__ import annotations

import asyncio
import inspect
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Union, get_args, get_origin

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

from app.logger import get_logger

from .agents_directory import agent_mapper
from .tools.models import ToolCall
from .tools.registry import ToolRegistry

logger = get_logger()


class AgentUnavailableError(Exception):
    """Signal that the model provider stayed irresponsive after retries.

    Raised by :meth:`ToolChoosingAgent.run_turn` only when bounded retries
    for retryable provider errors (429/503/504) are exhausted. The Engine
    catches this to stop the match; agents never decide winners themselves.
    """


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
                if origin is Union or (
                    hasattr(origin, "__origin__") and origin.__origin__ is Union
                ):  # type: ignore[attr-defined]
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
        self._tool_executor: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = (
            None
        )

        self._agent = Agent(
            model,
            output_type=[str, DeferredToolRequests],
            instructions=instructions,
            toolsets=[ExternalToolset(tool_defs)],
            capabilities=[HandleDeferredToolCalls(handler=self._handle_deferred_tools)],
        )

        self._message_history: list[Any] | None = None

        # Consecutive failed (non-scripted) turns. A single provider error
        # returns None so a transient blip doesn't kill the match, but a
        # persistently failing provider (e.g. a model/endpoint that never
        # supports tool use) raises AgentUnavailableError once the threshold
        # is reached, letting the Engine stop the match.
        self._consecutive_failures: int = 0

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
        produced nothing usable (scripted mode, isolated transient failure).
        Message history carries over across turns.

        Raises:
            AgentUnavailableError: if retryable provider errors (429/503/504)
                persist after bounded in-turn retries, or if non-retryable
                failures repeat across consecutive turns (the provider is
                never going to succeed). The Engine handles this by stopping
                the match.
        """
        if self._scripted_calls:
            call = self._scripted_calls.popleft()
            if call.name not in self.allowed_tools:
                raise ValueError(f"Agent selected unavailable tool {call.name!r}")
            if self._tool_executor is not None:
                await self._tool_executor(call.name, dict(call.arguments))
            return None
        if self._scripted_mode:
            return None

        prompt = "Work toward your objective. Call tools as needed, then reply with a brief status."
        if self.objective:
            prompt += f"\nCurrent match objective: {self.objective}"
        prompt += f"\nYour scratchpad:\n<scratchpad>{scratchpad}</scratchpad>"
        max_retries = 3
        last_status: int | None = None
        for _ in range(max_retries):
            try:
                result = await self._agent.run(
                    prompt, message_history=self._message_history
                )
                self._message_history = result.all_messages()
            except ModelHTTPError as e:
                status = e.status_code
                if status == 429:
                    last_status = status
                    logger.critical(f"Model rate limit exceeded: {e}")
                    raw_wait = e.headers.get("retry-after", 30) if e.headers else 30
                    try:
                        sleep_time = float(raw_wait)
                    except (ValueError, TypeError):
                        sleep_time = 30.0
                    await asyncio.sleep(sleep_time)
                    continue
                if status in (503, 504):
                    last_status = status
                    logger.critical(f"Model temporarily unavailable ({status}): {e}")
                    await asyncio.sleep(30.0)
                    continue
                logger.error(f"Model HTTP error: {e}")
                self._record_failure()
                return None
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                self._record_failure()
                return None
            if isinstance(result.output, str):
                self._consecutive_failures = 0
                return result.output
            logger.error(
                f"Unexpected agent output type: {type(result.output).__name__}"
            )
            self._record_failure()
            return None
        raise AgentUnavailableError(
            f"Model unavailable after {max_retries} retries"
            + (f" (last status {last_status})" if last_status is not None else "")
        )

    #: How many failed turns in a row before the agent is declared unavailable.
    _max_consecutive_failures: int = 3

    def _record_failure(self) -> None:
        """Count one failed turn; raise when the provider never recovers.

        A single failure returns None (transient blip); only persistent
        failure across consecutive turns raises, so the Engine stops the
        match instead of looping forever.
        """
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_consecutive_failures:
            raise AgentUnavailableError(
                f"Model unavailable after {self._consecutive_failures} "
                "consecutive failed turns"
            )
