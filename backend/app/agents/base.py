from __future__ import annotations

import asyncio
import inspect
import types
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Union, get_args, get_origin, get_type_hints
from uuid import uuid4

from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    RunContext,
    ToolDefinition,
    UsageLimits,
)
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.toolsets.external import ExternalToolset

from app.logger import get_logger

from .agents_directory import resolve_model
from .tools.models import ToolCall
from .tools.registry import ToolRegistry

logger = get_logger()


def _drop_pending_tool_calls(messages: list[Any]) -> list[Any]:
    """Drop a trailing model response whose tool calls have no results yet.

    pydantic-ai refuses to start a run when the supplied ``message_history`` ends
    on unprocessed tool calls (``Cannot provide a new user prompt when the
    message history contains unprocessed tool calls``), because the model would
    be asked a fresh question while its own calls were still outstanding.

    That is exactly the shape ``ctx.messages`` has inside the deferred-tool
    handler: the handler runs *before* the results it returns exist. The
    conversation pydantic-ai builds is only balanced again once those results
    are appended, so a snapshot taken there is unusable as a history until then.
    Trimming the incomplete tail keeps the prefix that is safe to resume from;
    the calls themselves are still recorded as match events.
    """
    trimmed = list(messages)
    returned = {
        part.tool_call_id
        for message in trimmed
        for part in getattr(message, "parts", ())
        if isinstance(part, ToolReturnPart)
    }
    while trimmed:
        pending = [
            part.tool_call_id
            for part in getattr(trimmed[-1], "parts", ())
            if isinstance(part, ToolCallPart)
        ]
        if not pending or all(tool_call_id in returned for tool_call_id in pending):
            break
        trimmed.pop()
    return trimmed


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


def dump_agent_history(agent: Any) -> list[dict[str, Any]] | None:
    """Return a JSON-safe dump of one agent's conversation, or ``None``.

    ``None`` means the object keeps no history -- a scripted or test double --
    so the caller can skip persisting it. pydantic-ai's own adapter is used, so
    the result loads back with ``ModelMessagesTypeAdapter.validate_python``.
    """
    history = getattr(agent, "message_history", None)
    messages = history() if callable(history) else history
    if not messages:
        return None
    return ModelMessagesTypeAdapter.dump_python(list(messages), mode="json")


def _function_signature_to_json_schema(tool: Any) -> dict[str, Any]:
    """Build a minimal JSON schema for a BaseTool's execute() method.

    Annotations are resolved with ``get_type_hints`` rather than read off
    ``inspect.Parameter.annotation``, because a module using ``from __future__
    import annotations`` -- the house style -- leaves every annotation a
    *string*. Reading them raw makes every argument look like an object, so the
    model is told ``bash(command=...)`` takes an object and cannot call it
    correctly. Resolving also keeps ``str | None`` working.
    """
    sig = inspect.signature(tool.execute)
    try:
        hints = get_type_hints(tool.execute)
    except Exception:  # unresolvable forward reference; fall back to raw
        hints = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in {"self", "context"}:
            continue
        schema: dict[str, Any] = {}
        annotation = hints.get(name, param.annotation)
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
                if origin is Union or origin is types.UnionType:
                    members = [m for m in get_args(annotation) if m is not type(None)]
                    types_found: list[str] = []
                    for m in members:
                        if m is str:
                            types_found.append("string")
                        elif m is int:
                            types_found.append("integer")
                        else:
                            types_found.append("object")
                    if len(types_found) == 1:
                        schema["type"] = types_found[0]
                    else:
                        schema["type"] = types_found
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


def _cost_note(tool: Any) -> str:
    """The price line appended to a match tool's model-facing description.

    Derived from ``BaseTool.cost`` instead of written into each description by
    hand, so the price the model is told and the price the Engine charges cannot
    drift apart. The reviewer's tools carry no ``cost`` at all -- there is no
    economy in a review -- and get no line.
    """
    cost = getattr(tool, "cost", None)
    if cost is None:
        return ""
    credits = int(cost)
    return "Costs no credits." if credits == 0 else f"Costs {credits} credits."


def _build_tool_definitions(
    registry: ToolRegistry, allowed_tools: set[str]
) -> list[ToolDefinition]:
    tool_defs: list[ToolDefinition] = []
    for name in allowed_tools:
        try:
            tool = registry.get(name)
        except KeyError:
            continue
        description = tool.description
        note = _cost_note(tool)
        if note:
            description = f"{description} {note}"
        tool_defs.append(
            ToolDefinition(
                name=tool.name,
                description=description,
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
        api_key: str | None = None,
        # _enqueued_messages: list[UserPromptPart] | None = None,
    ) -> None:
        # Every model is BYOK: the worker redeems the key its side was queued
        # with and passes it here, where the model client is built.
        model = resolve_model(model_name, api_key)
        self.allowed_tools = allowed_tools
        self.objective = objective
        self._enqueued_messages = []
        self._scripted_calls = deque(scripted_calls or ())
        self._scripted_mode = scripted_calls is not None

        if registry is None:
            from .tools.registry import build_default_registry

            registry = build_default_registry()
        self._registry = registry

        tool_defs = _build_tool_definitions(registry, allowed_tools)

        # Resolved per deferred request by the bound engine executor; None
        # until the engine binds it (standalone/scripted use has no executor).
        # The whole ToolCall is handed over, so the native tool-call id and its
        # response batch travel with it into the Engine.
        self._tool_executor: Callable[[ToolCall], Awaitable[Any]] | None = None

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
        executor: Callable[[ToolCall], Awaitable[Any]],
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
        # Snapshot the conversation pydantic-ai has built so far. ``run_turn``
        # only stores the history once a run *returns*, and the Engine cancels
        # an in-flight turn when the match ends -- a winning ``submit_flag``
        # ends it from inside the very run that would have stored the history,
        # which left both agents with nothing to save. pydantic-ai's own view is
        # already correct up to the request in flight.
        #
        # The trailing response is dropped because its tool calls have no
        # results yet: this handler is what produces them. Keeping it would
        # leave an unusable history behind if this run never returned, and the
        # next turn would be rejected outright.
        self._message_history = _drop_pending_tool_calls(list(ctx.messages))
        # One batch id for every call this response emitted: pydantic-ai puts
        # their results in a single message, so they are atomic to a replay.
        batch_id = str(uuid4())
        calls: dict[str, Any] = {}
        for request in requests.calls:
            call = ToolCall(
                name=request.tool_name,
                arguments=request.args_as_dict(),
                tool_call_id=request.tool_call_id,
                batch_id=batch_id,
            )
            try:
                calls[request.tool_call_id] = await self._tool_executor(call)
            except Exception as error:
                logger.error(f"Deferred tool executor failed: {error}")
                calls[request.tool_call_id] = {
                    "success": False,
                    "error": f"Tool execution failed: {error}",
                }
            for message in self._enqueued_messages:
                try:
                    ctx.enqueue(message)
                except Exception as error:
                    logger.error(f"Failed to enqueue agent message: {error}")
            self._enqueued_messages.clear()
        return requests.build_results(calls=calls)

    #: Hard cap on model requests within one turn. ``None`` defers to the
    #: provider. Match agents are paced by the Engine's turn loop and their
    #: own wall clock; a one-shot agent -- the reviewer -- has nothing else
    #: bounding it, so it sets this rather than looping until it runs out of
    #: context or budget.
    _request_limit: int | None = None

    def _turn_prompt(self, scratchpad: str) -> str:
        """The user prompt for one turn of a match-playing agent.

        The agent's credit balance is deliberately not here. A match agent
        spends almost a whole turn issuing tool call after tool call inside a
        single run, and this prompt is written once at the top of that run --
        the number would be stale from the first charge onward. The balance
        rides on every tool result instead (``ToolResult.credits``), which is
        the one channel that is refreshed per action. The price of each tool is
        in that tool's own description (see :func:`_cost_note`).

        Overridden by agents that are not playing a match and so have no
        objective or scratchpad to work toward.
        """
        prompt = "Work toward your objective. Call tools as needed, then reply with a brief status."
        if self.objective:
            prompt += f"\nCurrent match objective: {self.objective}"
        prompt += f"\nYour scratchpad:\n<scratchpad>{scratchpad}</scratchpad>"
        return prompt

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
                await self._tool_executor(call)
            return None
        if self._scripted_mode:
            return None

        prompt = self._turn_prompt(scratchpad)
        max_attempts = 3
        last_status: int | None = None
        history = self._usable_history()
        # Only sent when a limit is set, so an agent that does not opt in calls
        # the model exactly as it did before.
        run_kwargs: dict[str, Any] = {"message_history": history}
        if self._request_limit is not None:
            run_kwargs["usage_limits"] = UsageLimits(
                request_limit=self._request_limit
            )
        for attempt in range(1, max_attempts + 1):
            try:
                result = await self._agent.run(prompt, **run_kwargs)
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

    def _usable_history(self) -> list[Any]:
        """The history to resume from, ending on a resolved step.

        Last line of defence for the whole run path. A history left ending on
        unprocessed tool calls does not fail once -- it fails *every* time,
        because the Engine's turn loop simply retries after a failed turn, so
        the agent would be wedged until the match timed out. Dropping the
        incomplete tail costs the one response that never finished; the calls it
        contained are still recorded as match events.
        """
        history = list(self._message_history or [])
        trimmed = _drop_pending_tool_calls(history)
        if len(trimmed) != len(history):
            logger.warning(
                "Agent history ended on an unresolved tool call; resuming from "
                "the last completed step instead of failing every turn"
            )
            self._message_history = trimmed
        return trimmed

    def message_history(self) -> list[Any]:
        """This agent's pydantic-ai conversation so far (empty before a run)."""
        return list(self._message_history or [])

    def load_message_history(self, messages: list[dict[str, Any]]) -> None:
        """Seed this agent's conversation, resuming a forked match mid-history.

        ``messages`` is the JSON dump ``dump_agent_history`` produces from a
        parent match, already cut at the fork point, so the model continues
        knowing what it had already tried instead of starting from nothing.
        """
        self._message_history = list(ModelMessagesTypeAdapter.validate_python(messages))

    def inject_message(self, message: str):
        self._enqueued_messages.append(UserPromptPart(message))

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
