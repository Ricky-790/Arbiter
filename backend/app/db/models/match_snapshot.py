"""`match_snapshots` table: Solari snapshots of reconstructed fork states."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MatchSnapshot(Base):
    """One Solari snapshot of a match's state at one point in its history.

    The snapshot itself lives in Solari and is self-contained; this row is the
    index that lets a later fork skip rebuilding that state.

    ``match_id`` is the match whose history the snapshot reproduces -- the
    *source* match being forked from, not the fork whose sandbox happened to
    capture it -- and ``branch_event_id`` is how far along that history it
    goes. ``branch_event_timestamp`` duplicates that event's timestamp so
    "the newest snapshot at or before event E" is a single-table comparison
    rather than a join back to ``match_events``.
    """

    __tablename__ = "match_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "branch_event_id",
            name="uq_match_snapshots_match_branch",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("match_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    solari_snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
