"""Arbiter's observability boundary (Logfire-backed).

Engine, agents, and tools must import from here -- never ``import logfire``
directly -- so telemetry stays a side-effect that can never break a match.
All helpers degrade to no-ops until ``configure_observability()`` succeeds
(typically called once from the application entry point).
"""

from .logfire import (
    agent_observability_context,
    configure_observability,
    match_span,
    output_telemetry,
    record_match_event,
    set_span_attributes,
    tool_execution_span,
)

__all__ = [
    "agent_observability_context",
    "configure_observability",
    "match_span",
    "output_telemetry",
    "record_match_event",
    "set_span_attributes",
    "tool_execution_span",
]
