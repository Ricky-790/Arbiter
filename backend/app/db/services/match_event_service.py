"""Service for the `match_events` table."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MatchEvent

#: Allowed ``sort`` values for event listings.
MATCH_EVENT_SORTS = ("date_asc", "date_desc")


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


match_events_service = MatchEventService()
