"""Service for the `match_forks` table."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger

from ..db import get_session_factory
from ..models import MatchFork

logger = get_logger()

PENDING = "pending"
READY = "ready"
FAILED = "failed"


class MatchForkService:
    async def create_pending(
        self,
        *,
        parent_match_id: UUID,
        branch_event_id: UUID,
        branch_event_timestamp: datetime,
        session: AsyncSession,
    ) -> tuple[MatchFork, bool]:
        """Register a fork at one branch point, or return the existing one.

        Returns ``(fork, created)``. The unique key makes this idempotent: two
        requests for the same point get one fork, and the second is told it was
        not created so it does not queue a second rebuild.
        """
        statement = (
            pg_insert(MatchFork)
            .values(
                id=uuid4(),
                parent_match_id=parent_match_id,
                branch_event_id=branch_event_id,
                branch_event_timestamp=branch_event_timestamp,
                status=PENDING,
            )
            .on_conflict_do_nothing(constraint="uq_match_forks_parent_branch")
            .returning(MatchFork.id)
        )
        created_id = await session.scalar(statement)
        await session.commit()
        if created_id is not None:
            fork = await session.get(MatchFork, created_id)
            assert fork is not None
            return fork, True

        existing = await self.get_by_point(
            parent_match_id, branch_event_id, session
        )
        if existing is None:
            raise RuntimeError(
                f"Fork at event {branch_event_id} vanished after a conflict"
            )
        return existing, False

    async def get_fork(
        self, fork_id: UUID, session: AsyncSession
    ) -> MatchFork | None:
        """Return one fork by id, or ``None``."""
        return await session.get(MatchFork, fork_id)

    async def get_by_point(
        self,
        parent_match_id: UUID,
        branch_event_id: UUID,
        session: AsyncSession,
    ) -> MatchFork | None:
        """Return the fork at one branch point of one match, or ``None``."""
        result = await session.execute(
            select(MatchFork).where(
                MatchFork.parent_match_id == parent_match_id,
                MatchFork.branch_event_id == branch_event_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_ready_at_or_before(
        self,
        parent_match_id: UUID,
        event_timestamp: datetime,
        event_id: UUID,
        session: AsyncSession,
    ) -> MatchFork | None:
        """Return the newest ready fork not after one event.

        ``(timestamp, id)`` is ``match_events``' total order, so this is the
        closest already-rebuilt state that can serve as the base for a new
        fork, meaning only the gap between them has to be replayed.
        """
        result = await session.execute(
            select(MatchFork)
            .where(
                MatchFork.parent_match_id == parent_match_id,
                MatchFork.status == READY,
                MatchFork.solari_snapshot_id.is_not(None),
                or_(
                    MatchFork.branch_event_timestamp < event_timestamp,
                    and_(
                        MatchFork.branch_event_timestamp == event_timestamp,
                        MatchFork.branch_event_id <= event_id,
                    ),
                ),
            )
            .order_by(
                MatchFork.branch_event_timestamp.desc(),
                MatchFork.branch_event_id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_ready(
        self,
        fork_id: UUID,
        *,
        snapshot_id: str,
        prisoner_messages: list[dict[str, Any]] | None,
        warden_messages: list[dict[str, Any]] | None,
        session: AsyncSession,
    ) -> None:
        """Record the rebuilt state and open the fork for starting matches."""
        await session.execute(
            update(MatchFork)
            .where(MatchFork.id == fork_id)
            .values(
                status=READY,
                solari_snapshot_id=snapshot_id,
                prisoner_messages=prisoner_messages,
                warden_messages=warden_messages,
            )
        )
        await session.commit()

    async def mark_failed(self, fork_id: UUID, session: AsyncSession) -> None:
        """Mark a fork whose rebuild failed so it is not mistaken for ready."""
        await session.execute(
            update(MatchFork)
            .where(MatchFork.id == fork_id)
            .values(status=FAILED)
        )
        await session.commit()

    async def requeue(self, fork_id: UUID, session: AsyncSession) -> None:
        """Put a failed fork back to ``pending`` so it can be rebuilt."""
        await session.execute(
            update(MatchFork)
            .where(MatchFork.id == fork_id)
            .values(status=PENDING)
        )
        await session.commit()

    async def list_forks(
        self,
        session: AsyncSession,
        *,
        parent_match_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[MatchFork], int]:
        """Return one page of saved forks, newest first.

        ``parent_match_id`` narrows it to one match's forks; ``None`` lists
        every saved fork.
        """
        condition = (
            (MatchFork.parent_match_id == parent_match_id,)
            if parent_match_id is not None
            else ()
        )
        total = (
            await session.scalar(
                select(func.count()).select_from(MatchFork).where(*condition)
            )
            or 0
        )
        result = await session.execute(
            select(MatchFork)
            .where(*condition)
            .order_by(MatchFork.created_at.desc(), MatchFork.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total


match_forks_service = MatchForkService()


async def fail_fork(fork_id: UUID) -> None:
    """Mark a fork failed using its own session. Never raises.

    Called from the fork worker's failure path, where the task is already
    unwinding and must not be replaced by a second error.
    """
    try:
        factory = get_session_factory()
        async with factory() as session:
            await match_forks_service.mark_failed(fork_id, session)
    except Exception:
        logger.exception(f"Failed to mark fork {fork_id} as failed")
