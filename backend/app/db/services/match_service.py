"""Service for the `matches` table."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Match

#: Allowed ``sort`` values for match listings.
MATCH_SORTS = ("date_desc", "date_asc")

#: Columns an update is allowed to touch.
_UPDATABLE_COLUMNS = frozenset(
    {
        "status",
        "winner",
        "duration_seconds",
        "started_at",
        "finished_at",
    }
)


class MatchService:
    async def list_matches(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        sort: str = "date_desc",
    ) -> tuple[list[Match], int]:
        """Return one page of matches and the total row count.

        Sorted by ``created_at`` (newest first by default). ``id`` is a
        tie-breaker so pagination stays stable when timestamps are equal.
        """
        total = await session.scalar(select(func.count()).select_from(Match)) or 0
        order = (
            Match.created_at.asc() if sort == "date_asc" else Match.created_at.desc()
        )
        result = await session.execute(
            select(Match)
            .order_by(order, Match.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def get_match(
        self, match_id: UUID, session: AsyncSession
    ) -> Match | None:
        """Return one match row (with its challenge loaded) or None."""
        return await session.get(Match, match_id)

    async def create_queued_match(
        self,
        session: AsyncSession,
        *,
        match_id: UUID,
        challenge_id: UUID,
        prisoner_model: str,
        prisoner_provider: str,
        warden_model: str,
        warden_provider: str,
        win_condition: str,
    ) -> Match:
        """Insert the match row the moment it is queued.

        ``ON CONFLICT DO NOTHING`` on the primary key keeps this idempotent, so
        a replayed request can never create a second record for one match. The
        worker and Engine only ever update this row afterwards.
        """
        statement = (
            pg_insert(Match)
            .values(
                id=match_id,
                challenge_id=challenge_id,
                prisoner_model=prisoner_model,
                prisoner_provider=prisoner_provider,
                warden_model=warden_model,
                warden_provider=warden_provider,
                status="queued",
                win_condition=win_condition,
            )
            .on_conflict_do_nothing(index_elements=[Match.id])
        )
        await session.execute(statement)
        await session.commit()
        match = await session.get(Match, match_id)
        if match is None:
            raise RuntimeError(f"Failed to persist queued match {match_id}")
        return match

    async def set_status(
        self,
        session: AsyncSession,
        match_id: UUID,
        status: str,
        **fields: Any,
    ) -> None:
        """Update a match's lifecycle fields (status, winner, timestamps...)."""
        values = {
            key: value for key, value in fields.items() if key in _UPDATABLE_COLUMNS
        }
        values["status"] = status
        await session.execute(
            update(Match).where(Match.id == match_id).values(**values)
        )
        await session.commit()


matches_service = MatchService()
