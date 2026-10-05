"""Service for the `strategies` table."""

from __future__ import annotations

from typing import Iterable, NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Challenge, Strategy

#: Longest label derived from a strategy's text. Long enough for a full
#: sentence, short enough for a list row.
MAX_ONE_LINE_LENGTH = 200


def one_line_description(strategy: str) -> str:
    """Derive the short label a strategy is listed under.

    The promotion endpoint takes no description -- it would just be a second
    thing to keep in sync with the text -- so the label is taken from the
    strategy itself: its first non-blank line, truncated if it runs long. A
    strategy with no text at all is rejected before it gets here, so an empty
    label means the caller skipped that check.
    """
    first_line = ""
    for line in strategy.splitlines():
        if line.strip():
            first_line = line.strip()
            break
    if len(first_line) <= MAX_ONE_LINE_LENGTH:
        return first_line
    return first_line[: MAX_ONE_LINE_LENGTH - 1].rstrip() + "\u2026"


class StrategyRow(NamedTuple):
    """A strategy plus the name of the challenge it was played on.

    The name is joined in rather than reached through a relationship: loading a
    ``Challenge`` eagerly loads its ``matches``, so a ``Strategy.challenge``
    relationship would make listing the library drag in every match of every
    challenge it touches.
    """

    strategy: Strategy
    challenge_name: str | None


class StrategyService:
    async def get_strategy(
        self, strategy_id: UUID, session: AsyncSession
    ) -> Strategy | None:
        """Return one saved strategy, or None."""
        return await session.get(Strategy, strategy_id)

    async def get_strategy_row(
        self, strategy_id: UUID, session: AsyncSession
    ) -> StrategyRow | None:
        """Return one saved strategy with its challenge's name, or None."""
        result = await session.execute(
            select(Strategy, Challenge.name)
            .join(Challenge, Challenge.id == Strategy.challenge_id, isouter=True)
            .where(Strategy.id == strategy_id)
        )
        row = result.first()
        return None if row is None else StrategyRow(row[0], row[1])

    async def list_strategies(
        self,
        session: AsyncSession,
        *,
        offset: int,
        limit: int,
        challenge_id: UUID | None = None,
    ) -> tuple[list[StrategyRow], int]:
        """Return one page of the library, newest first, and the total count.

        ``challenge_id`` narrows it to one challenge. A strategy is only
        meaningful against the challenge it was played on, so this is the
        natural way to ask "what has been tried here".

        ``id`` breaks ties on ``created_at`` so paging cannot skip or repeat a
        row when several strategies are promoted in the same instant. The caller
        owns the bounds; ``limit`` is not clamped here.
        """
        conditions = []
        if challenge_id is not None:
            conditions.append(Strategy.challenge_id == challenge_id)

        total = (
            await session.scalar(
                select(func.count()).select_from(Strategy).where(*conditions)
            )
            or 0
        )
        result = await session.execute(
            select(Strategy, Challenge.name)
            .join(Challenge, Challenge.id == Strategy.challenge_id, isouter=True)
            .where(*conditions)
            .order_by(Strategy.created_at.desc(), Strategy.id)
            .offset(offset)
            .limit(limit)
        )
        return [StrategyRow(row[0], row[1]) for row in result.all()], total

    async def get_strategies(
        self, strategy_ids: Iterable[UUID], session: AsyncSession
    ) -> dict[UUID, Strategy]:
        """Return the saved strategies matching ``strategy_ids``, keyed by id.

        Missing ids are simply absent from the result; the caller decides
        whether that is an error.
        """
        wanted = list(dict.fromkeys(strategy_ids))
        if not wanted:
            return {}
        result = await session.execute(
            select(Strategy).where(Strategy.id.in_(wanted))
        )
        return {row.id: row for row in result.scalars().all()}

    async def find_for_match(
        self, match_id: UUID, user: str, session: AsyncSession
    ) -> Strategy | None:
        """Return the match's saved strategy for one side, if it has one."""
        result = await session.execute(
            select(Strategy).where(
                Strategy.match_id == match_id, Strategy.user == user
            )
        )
        return result.scalars().first()

    async def create_for_match(
        self,
        session: AsyncSession,
        *,
        match_id: UUID,
        challenge_id: UUID,
        user: str,
        strategy: str,
        origin_strat_id: UUID | None = None,
    ) -> Strategy:
        """Promote one side's strategy out of a match into the library.

        ``(match_id, user)`` is unique, so promoting the same side twice keeps
        the first row and changes nothing -- including its ``origin_strat_id``,
        which makes a repeated call safe rather than a way to rewrite lineage.
        The stored row is returned either way.
        """
        statement = (
            pg_insert(Strategy)
            .values(
                match_id=match_id,
                challenge_id=challenge_id,
                user=user,
                one_line_description=one_line_description(strategy),
                strategy=strategy,
                origin_strat_id=origin_strat_id,
            )
            .on_conflict_do_nothing(constraint="uq_strategies_match_user")
        )
        await session.execute(statement)
        await session.commit()

        stored = await self.find_for_match(match_id, user, session)
        if stored is None:
            raise RuntimeError(
                f"Failed to persist the {user} strategy of match {match_id}"
            )
        return stored


strategies_service = StrategyService()
