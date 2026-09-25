"""Load persisted match activity as scripted tool calls."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.agents.models import AgentType
from app.agents.tools.models import ToolCall
from app.db import get_session_factory
from app.db.models import MatchEvent

from .models import ScriptedToolCall


async def get_scripted_calls(
    fork_match_id: UUID,
    match_event_id: UUID,
) -> list[ScriptedToolCall]:
    """Return actor-aware tool calls from a match through its branch event."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(MatchEvent)
            .where(MatchEvent.match_id == fork_match_id)
            .order_by(MatchEvent.timestamp.asc(), MatchEvent.id.asc())
        )
        events = list(result.scalars().all())

    events.sort(key=lambda event: (event.timestamp, event.id))
    branch_index = next(
        (index for index, event in enumerate(events) if event.id == match_event_id),
        None,
    )
    if branch_index is None:
        raise ValueError(
            f"Match event {match_event_id} does not belong to match {fork_match_id}"
        )

    calls: list[ScriptedToolCall] = []
    for event in events[: branch_index + 1]:
        if event.event_type != "tool_call":
            continue
        action = event.action
        tool_name = action.get("tool")
        arguments = action.get("arguments", {})
        if not isinstance(tool_name, str) or not isinstance(arguments, dict):
            raise ValueError(f"Invalid tool_call action in event {event.id}")
        try:
            actor = AgentType(event.actor)
        except ValueError as error:
            raise ValueError(f"Invalid actor in event {event.id}") from error
        calls.append(
            ScriptedToolCall(
                tool=ToolCall(name=tool_name, arguments=arguments),
                timestamp=event.timestamp,
                actor=actor,
            )
        )
    calls.sort(key=lambda call: call.timestamp)
    return calls
