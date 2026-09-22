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


def with_tips(instructions: str, tips: str | None) -> str:
    """Append optional operator tips to an agent's base role instructions.

    Tips come from the match request (``prisoner_suggestions`` /
    ``warden_suggestions``). Empty or whitespace-only input is ignored, so a
    blank form field leaves the role instructions untouched.
    """
    if tips is None or tips.strip() == "":
        return instructions
    return f"{instructions}\n\nTips: {tips.strip()}"


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
                elif origin is dict:
                    # Free-form JSON object (e.g. a structured flag submission).
                    schema["type"] = "object"
                    schema["additionalProperties"] = True
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

        # Bound by the Engine so retryable provider failures (rate limits,
        # 503/504) reach the match log and the spectator stream. Best-effort:
        # reporting must never break a turn.
        self._event_reporter: (
            Callable[[str, dict[str, Any]], Awaitable[None]] | None
        ) = None

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

    def bind_event_reporter(
        self,
        reporter: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Bind the engine's match-event reporter for provider-level events."""
        self._event_reporter = reporter

    async def _report_event(self, event_type: str, **attributes: Any) -> None:
        """Report one provider event without ever breaking the turn."""
        if self._event_reporter is None:
            return
        try:
            await self._event_reporter(event_type, attributes)
        except Exception:
            logger.exception("Agent event reporter failed")

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
        max_attempts = 3
        last_status: int | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = await self._agent.run(
                    prompt, message_history=self._message_history
                )
                self._message_history = result.all_messages()
            except ModelHTTPError as e:
                status = e.status_code
                if status not in self._RETRYABLE_STATUSES:
                    logger.error(f"Model HTTP error: {e}")
                    await self._report_event(
                        "agent_error",
                        reason="model_http_error",
                        status=status,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        detail=str(e),
                    )
                    self._record_failure()
                    return None

                last_status = status
                logger.critical(f"Model provider error ({status}): {e}")
                if attempt == max_attempts:
                    # Nothing is left to wait for. Sleeping on the final
                    # failure only delays the Engine terminating the match.
                    break

                wait = self._retry_wait(e, status=status)
                await self._report_event(
                    "agent_retry",
                    reason="rate_limit" if status == 429 else "model_unavailable",
                    status=status,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    wait_seconds=wait,
                )
                await asyncio.sleep(wait)
                continue
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await self._report_event(
                    "agent_error",
                    reason="unexpected_error",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    detail=str(e),
                )
                self._record_failure()
                return None
            if isinstance(result.output, str):
                self._consecutive_failures = 0
                return result.output
            logger.error(
                f"Unexpected agent output type: {type(result.output).__name__}"
            )
            await self._report_event(
                "agent_error",
                reason="unexpected_output_type",
                attempt=attempt,
                max_attempts=max_attempts,
                detail=type(result.output).__name__,
            )
            self._record_failure()
            return None
        raise AgentUnavailableError(
            f"Model unavailable after {max_attempts} attempts"
            + (f" (last status {last_status})" if last_status is not None else "")
        )

    #: Provider statuses worth another attempt within the same turn.
    _RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 503, 504})

    #: Upper bound on a provider-requested wait. A large ``Retry-After`` must
    #: not consume the match's remaining wall-clock budget.
    _max_retry_wait_seconds: float = 60.0

    #: Wait used when the provider gives no usable ``Retry-After``.
    _default_retry_wait_seconds: float = 30.0

    @classmethod
    def _retry_wait(cls, error: ModelHTTPError, *, status: int) -> float:
        """Seconds to wait before the next attempt, honouring ``Retry-After``.

        The header is only read for rate limits and is clamped to
        :attr:`_max_retry_wait_seconds`; a missing, non-numeric or HTTP-date
        value falls back to :attr:`_default_retry_wait_seconds`.
        """
        if status != 429 or not error.headers:
            return cls._default_retry_wait_seconds
        raw = error.headers.get("retry-after")
        try:
            wait = float(raw) if raw is not None else cls._default_retry_wait_seconds
        except (TypeError, ValueError):
            return cls._default_retry_wait_seconds
        return max(0.0, min(wait, cls._max_retry_wait_seconds))

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
