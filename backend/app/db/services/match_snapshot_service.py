"""Service for the `match_snapshots` table."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger

from ..db import get_session_factory
from ..models import MatchSnapshot

logger = get_logger()


class MatchSnapshotService:
    async def get_snapshot_at_or_before(
        self,
        match_id: UUID,
        event_timestamp: datetime,
        event_id: UUID,
        session: AsyncSession,
    ) -> MatchSnapshot | None:
        """Return the newest snapshot of ``match_id`` at or before one event.

        ``(timestamp, id)`` is ``match_events``' total order, so this returns
        the latest branch point that is not after ``event_id``. A snapshot
        taken exactly at that event therefore beats an earlier one.
        """
        result = await session.execute(
            select(MatchSnapshot)
            .where(
                MatchSnapshot.match_id == match_id,
                or_(
                    MatchSnapshot.branch_event_timestamp < event_timestamp,
                    and_(
                        MatchSnapshot.branch_event_timestamp == event_timestamp,
                        MatchSnapshot.branch_event_id <= event_id,
                    ),
                ),
            )
            .order_by(
                MatchSnapshot.branch_event_timestamp.desc(),
                MatchSnapshot.branch_event_id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def store_snapshot(
        self,
        *,
        match_id: UUID,
        branch_event_id: UUID,
        branch_event_timestamp: datetime,
        solari_snapshot_id: str,
        session: AsyncSession,
    ) -> MatchSnapshot | None:
        """Record one snapshot for a branch point.

        Returns the stored row, or ``None`` when a snapshot already existed
        there: the unique constraint makes two forks of the same point
        idempotent instead of duplicating stored state.
        """
        statement = (
            pg_insert(MatchSnapshot)
            .values(
                id=uuid4(),
                match_id=match_id,
                branch_event_id=branch_event_id,
                branch_event_timestamp=branch_event_timestamp,
                solari_snapshot_id=solari_snapshot_id,
            )
            .on_conflict_do_nothing(constraint="uq_match_snapshots_match_branch")
            .returning(MatchSnapshot.id)
        )
        inserted_id = await session.scalar(statement)
        await session.commit()
        if inserted_id is None:
            return None
        return await session.get(MatchSnapshot, inserted_id)


match_snapshots_service = MatchSnapshotService()


async def store_match_snapshot(
    *,
    match_id: UUID,
    branch_event_id: UUID,
    branch_event_timestamp: datetime,
    solari_snapshot_id: str,
) -> bool:
    """Record one fork snapshot using its own session. Never raises.

    Returns ``True`` when this call stored the snapshot, ``False`` when one
    already existed for that branch point or persistence failed -- the caller
    is taking a snapshot for later reuse, so a storage failure must not affect
    the match that is currently running.
    """
    try:
        factory = get_session_factory()
        async with factory() as session:
            stored = await match_snapshots_service.store_snapshot(
                match_id=match_id,
                branch_event_id=branch_event_id,
                branch_event_timestamp=branch_event_timestamp,
                solari_snapshot_id=solari_snapshot_id,
                session=session,
            )
        return stored is not None
    except Exception:
        logger.exception(
            f"Failed to store fork snapshot for match {match_id} "
            f"at event {branch_event_id}"
        )
        return False
