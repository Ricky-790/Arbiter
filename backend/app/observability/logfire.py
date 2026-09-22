from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

import logfire
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor
from pydantic import BaseModel

from app.logger import get_logger
from app.observability.models import MatchSpanAttributes, ToolSpanAttributes

logger = get_logger()

# Context
_current_match_id: ContextVar[str | None] = ContextVar(
    "arbiter_match_id",
    default=None,
)

_current_agent_role: ContextVar[str | None] = ContextVar(
    "arbiter_agent_role",
    default=None,
)


# Logfire configuration
def scrubbing_callback(m: logfire.ScrubMatch):
    return m.value


def configure_observability(
    *,
    service_name: str = "arbiter-project",
    service_version: str | None = None,
    environment: str | None = None,
) -> None:
    """Configure Logfire and Pydantic AI instrumentation."""

    logfire.configure(
        service_name=service_name,
        service_version=service_version or os.getenv("SERVICE_VERSION"),
        environment=environment or os.getenv("DEPLOYMENT_ENVIRONMENT", "dev"),
        scrubbing=logfire.ScrubbingOptions(callback=scrubbing_callback),
    )

    logfire.instrument_pydantic_ai(include_content=True)

    # Pydantic AI creates the agent/chat/tool spans.
    # This processor adds Arbiter-specific attributes to them.
    trace.get_tracer_provider().add_span_processor(ArbiterSpanProcessor())


class ArbiterSpanProcessor(SpanProcessor):
    """Add Arbiter context to Pydantic AI spans created during a match."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        match_id = _current_match_id.get()

        if match_id is None:
            return

        attributes = getattr(span, "attributes", {})

        operation = attributes.get("gen_ai.operation.name")

        if operation == "invoke_agent":
            span_type = "agent"
        elif operation == "chat":
            span_type = "chat"
        elif operation == "execute_tool":
            span_type = "tool"
        else:
            return

        span.set_attributes(
            {
                "arbiter.span_type": span_type,
                "arbiter.match_id": match_id,
                "arbiter.agent_role": _current_agent_role.get(),
            }
        )

    def on_end(self, span: Any) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


@contextmanager
def match_span(
    *,
    match_id: str,
    challenge_id: str,
) -> Iterator[Any]:
    """Create the root span for one complete Arbiter match."""

    token = _current_match_id.set(match_id)

    attributes = MatchSpanAttributes(
        match_id=match_id,
        challenge_id=challenge_id,
    )

    try:
        with logfire.span(
            f"match {match_id}",
            **attributes.to_attributes(),
        ) as span:
            yield span
    finally:
        _current_match_id.reset(token)


@contextmanager
def agent_observability_context(
    *,
    agent_role: str,
) -> Iterator[None]:
    """Attach an agent role to all spans created during this agent run."""

    token = _current_agent_role.set(agent_role)

    try:
        yield
    finally:
        _current_agent_role.reset(token)


@contextmanager
def tool_execution_span(
    *, match_id: str, agent_role: str, tool_name: str, tool_args: dict
) -> Iterator[Any]:
    """Create one span for the complete Engine-side tool request."""

    attributes = ToolSpanAttributes(
        match_id=match_id,
        agent_role=agent_role,
        tool_name=tool_name,
        tool_args=tool_args,
    )

    with logfire.span(
        f"tool execution {agent_role}.{tool_name}",
        **attributes.to_attributes(),
    ) as span:
        yield span


def set_span_attributes(
    span: Any,
    attributes: BaseModel | dict[str, Any],
) -> None:
    """Update an existing span with additional telemetry."""

    if isinstance(attributes, BaseModel):
        values = attributes.model_dump(exclude_none=True)

        # Pydantic models use normal field names.
        # Convert them to Arbiter's telemetry namespace.
        values = {f"arbiter.{key}": value for key, value in values.items()}
    else:
        values = {
            key if key.startswith("arbiter.") else f"arbiter.{key}": value
            for key, value in attributes.items()
            if value is not None
        }

    span.set_attributes(values)


def record_match_event(
    event: str,
    /,
    **attributes: Any,
) -> None:
    """Record a discrete event inside the current match trace."""

    logfire.info(
        "match event {event}",
        event=event,
        **attributes,
    )


def output_telemetry(
    output: str | None,
) -> dict[str, Any]:
    """Return a bounded representation of tool output."""

    text = output or ""

    try:
        limit = int(os.getenv("OBS_OUTPUT_PREVIEW_CHARS", "2000"))
    except (TypeError, ValueError):
        limit = 2000

    return {
        "output_size": len(text),
        "output_truncated": len(text) > limit,
        "output_preview": text[:limit],
    }


configure_observability()
