"""Service for the `matches` table."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
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

    async def list_matches_using_strategy(
        self,
        session: AsyncSession,
        strategy_id: UUID,
        *,
        exclude_match_id: UUID | None = None,
        offset: int,
        limit: int,
    ) -> tuple[list[Match], int]:
        """Return one page of the matches started from one saved strategy.

        A match records the strategies it ran on ``matches.strategy_id``, a map
        keyed by side, so "used this strategy" means either side's entry names
        it. That is the only link: the text itself is copied onto the match, so
        two matches sharing wording are not related.

        ``exclude_match_id`` drops the match the strategy was promoted *from*.
        It points at its own strategy -- promotion writes the id back onto it --
        but it was not started from it, and counting it would put the same match
        in both halves of a lineage.

        Newest first, with ``id`` breaking ties on ``created_at`` so paging
        cannot skip or repeat a row. The caller owns the bounds.
        """
        condition = or_(
            Match.strategy_id["prisoner"].astext == str(strategy_id),
            Match.strategy_id["warden"].astext == str(strategy_id),
        )
        if exclude_match_id is not None:
            condition = and_(condition, Match.id != exclude_match_id)

        total = (
            await session.scalar(
                select(func.count()).select_from(Match).where(condition)
            )
            or 0
        )
        result = await session.execute(
            select(Match)
            .where(condition)
            .order_by(Match.created_at.desc(), Match.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

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
        parent_match_id: UUID | None = None,
        branch_event_id: UUID | None = None,
        strategy: dict[str, str] | None = None,
        strategy_id: dict[str, str] | None = None,
    ) -> Match:
        """Insert the match row the moment it is queued.

        ``parent_match_id`` and ``branch_event_id`` record lineage for a fork:
        the match it branched from and the event it branched at. Both default
        to ``None``, which is what a match started from scratch gets.

        ``strategy`` is the text each side was started with, keyed by side, so
        the self-improvement loop can promote it later. ``strategy_id`` is the
        library row that text came from, for a side started from a saved
        strategy -- recording it here is what makes "which matches ran this
        strategy" answerable, since the text is copied onto the match and two
        matches sharing wording are not otherwise related.

        Sides with no strategy are left out of both, and an empty mapping stores
        ``NULL``.

        ``ON CONFLICT DO NOTHING`` on the primary key keeps this idempotent, so
        a replayed request can never create a second record for one match. The
        worker and Engine only ever update this row afterwards.
        """
        statement = (
            pg_insert(Match)
            .values(
                id=match_id,
                parent_match_id=parent_match_id,
                branch_event_id=branch_event_id,
                challenge_id=challenge_id,
                prisoner_model=prisoner_model,
                prisoner_provider=prisoner_provider,
                warden_model=warden_model,
                warden_provider=warden_provider,
                status="queued",
                win_condition=win_condition,
                strategy=strategy or None,
                strategy_id=strategy_id or None,
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

    async def set_match_strategy_id(
        self,
        session: AsyncSession,
        match_id: UUID,
        user: str,
        strategy_id: UUID,
    ) -> bool:
        """Record which saved strategy one side of a match was promoted to.

        ``matches.strategy_id`` is keyed by side, so this merges one key rather
        than replacing the object -- the other side's entry, if it has one, is
        preserved. Returns ``False`` when the match does not exist.

        Stored as a string because the map lives in JSONB; readers convert back
        to ``UUID``.
        """
        match = await session.get(Match, match_id)
        if match is None:
            return False
        merged = dict(match.strategy_id or {})
        merged[user] = str(strategy_id)
        match.strategy_id = merged
        await session.commit()
        return True


matches_service = MatchService()
