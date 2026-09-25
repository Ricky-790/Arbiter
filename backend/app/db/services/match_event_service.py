"""Service for the `match_events` table."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MatchEvent

#: Allowed ``sort`` values for event listings.
MATCH_EVENT_SORTS = ("date_asc", "date_desc")

#: ``event_type`` of a persisted agent tool request.
TOOL_CALL_EVENT_TYPE = "tool_call"


class MatchEventService:
    async def get_match_events(
        self,
        match_id: UUID,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        sort: str = "date_asc",
    ) -> tuple[list[MatchEvent], int]:
        """Return one page of a match's events and the total row count.

        Sorted by ``timestamp`` (oldest first by default). ``id`` is a
        tie-breaker so pagination stays stable when timestamps are equal.
        """
        condition = MatchEvent.match_id == match_id
        total = (
            await session.scalar(
                select(func.count()).select_from(MatchEvent).where(condition)
            )
            or 0
        )
        order = (
            MatchEvent.timestamp.desc()
            if sort == "date_desc"
            else MatchEvent.timestamp.asc()
        )
        result = await session.execute(
            select(MatchEvent)
            .where(condition)
            .order_by(order, MatchEvent.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def get_match_event(
        self,
        event_id: UUID,
        session: AsyncSession,
    ) -> MatchEvent | None:
        """Return one event row by id, or ``None``."""
        return await session.get(MatchEvent, event_id)

    async def get_tool_calls_until_event(
        self,
        match_id: UUID,
        event_id: UUID,
        session: AsyncSession,
        *,
        after_event_id: UUID | None = None,
    ) -> list[MatchEvent] | None:
        """Return a match's persisted tool calls up to and including ``event_id``.

        This is the history a fork replays: every ``tool_call`` row from the
        start of the match through the branch event. Rows come back oldest
        first in ``(timestamp, id)`` order -- the same total order the event
        listings paginate by -- so the caller can re-run them in the order they
        originally happened.

        ``after_event_id`` bounds the window from below, exclusively: it is the
        branch point of a snapshot the caller is rebooting from, so only the
        events recorded after it still need replaying.

        Returns ``None`` when ``event_id`` -- or a supplied ``after_event_id``
        -- is not an event of ``match_id``. The caller treats the first as a
        real error and the second as an unusable snapshot, falling back to a
        full rebuild rather than replaying a whole match on top of a restored
        snapshot.
        """
        events = list(
            (
                await session.execute(
                    select(MatchEvent)
                    .where(MatchEvent.match_id == match_id)
                    .order_by(MatchEvent.timestamp.asc(), MatchEvent.id.asc())
                )
            )
            .scalars()
            .all()
        )
        branch_index = next(
            (index for index, event in enumerate(events) if event.id == event_id),
            None,
        )
        if branch_index is None:
            return None
        start = 0
        if after_event_id is not None:
            after_index = next(
                (
                    index
                    for index, event in enumerate(events)
                    if event.id == after_event_id
                ),
                None,
            )
            if after_index is None:
                return None
            start = after_index + 1
        return [
            event
            for event in events[start : branch_index + 1]
            if event.event_type == TOOL_CALL_EVENT_TYPE
        ]


match_events_service = MatchEventService()
