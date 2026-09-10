from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

import logfire

from app.logger import get_logger

logger = get_logger()


def configure_observability(
    *,
    service_name: str = "arbiter-project",
    service_version: str | None = None,
    environment: str | None = None,
) -> bool:
    """Configure Logfire and enable Pydantic AI instrumentation.

    Must be called once per process, before any instrumented code runs
    (i.e. from the application entry point). Safe to call repeatedly and
    safe when the ``logfire`` package is not installed yet -- returns False
    and leaves telemetry disabled instead of raising.
    """
    try:
        logfire.configure(
            service_name=service_name,
            service_version=service_version or os.getenv("SERVICE_VERSION"),
            environment=environment or os.getenv("DEPLOYMENT_ENVIRONMENT", "dev"),
        )
        logfire.instrument_pydantic_ai()
    except Exception:
        logger.exception("logfire configuration failed; observability disabled")
        return False
    _enabled = True
    return True


configure_observability()


def is_enabled() -> bool:
    return True


@contextmanager
def tool_execution_span(
    *, match_id: str, actor: str, tool: str
) -> Iterator[Any | None]:
    """Span covering one Engine tool-call decision (requested -> outcome).

    Duration (tool-execution latency) is recorded automatically. Yields None
    when telemetry is disabled so callers never branch on availability.
    Exceptions from the wrapped body propagate normally after being recorded.
    """
    if not is_enabled():
        yield None
        return
    try:
        span_cm = logfire.span(
            "tool execution {actor}.{tool}",
            match_id=match_id,
            actor=actor,
            tool=tool,
            stage="requested",
        )
    except Exception:
        logger.warning("tool_execution_span unavailable; continuing without span")
        yield None
        return
    with span_cm as span:
        yield span


def set_span_attributes(span: Any | None, attributes: dict[str, Any]) -> None:
    """Attach structured attributes to a span; no-op when span is None.

    ``None`` values are dropped (OpenTelemetry attributes cannot be null).
    """
    if span is None or not is_enabled():
        return
    try:
        span.set_attributes(
            {key: value for key, value in attributes.items() if value is not None}
        )
    except Exception:
        logger.warning("failed to set span attributes")


def record_match_event(event: str, /, **attributes: Any) -> None:
    """Record a match-lifecycle event (started/finished/trap_triggered)."""
    if not is_enabled():
        return
    try:
        logfire.info("match event {event}", event=event, **attributes)
    except Exception:
        logger.warning("failed to record match event")


def _preview_limit() -> int:
    try:
        return int(os.getenv("OBS_OUTPUT_PREVIEW_CHARS", "2000"))
    except (TypeError, ValueError):
        return 2000


def output_telemetry(output: str | None) -> dict[str, Any]:
    """Bounded representation of tool output for telemetry.

    Never sends unlimited stdout/stderr: records size, whether it was cut,
    and a preview. Success/exit_code travel as separate span attributes.
    """
    text = output or ""
    limit = _preview_limit()
    return {
        "output_size": len(text),
        "output_truncated": len(text) > limit,
        "output_preview": text[:limit],
    }
