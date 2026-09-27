"""`match_forks` table: saved fork points a match can be started from."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

#: A fork's lifecycle. ``pending`` while its snapshot is being rebuilt,
#: ``ready`` once it can be started from, ``failed`` if the rebuild failed.
FORK_STATUSES = ("pending", "ready", "failed")


class MatchFork(Base):
    """One saved fork: a match's state at one event, ready to be started from.

    ``parent_match_id`` is the match being forked and ``branch_event_id`` the
    point in its history the fork resumes from -- always the *effective* point
    after snapping to the end of a model response. That pair is unique, so
    asking for the same point twice yields the same fork.

    ``solari_snapshot_id`` and the two conversations are filled in by the fork
    worker once it has rebuilt that state; until then ``status`` is
    ``pending``.

    A fork is deliberately *not* a match. It carries no models and never runs:
    a match is started from it later, with whatever models and instructions the
    caller wants, which is the whole point of keeping a fork around.
    """

    __tablename__ = "match_forks"
    __table_args__ = (
        UniqueConstraint(
            "parent_match_id",
            "branch_event_id",
            name="uq_match_forks_parent_branch",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parent_match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "matches.id",
            name="fk_match_forks_parent_match_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    branch_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "match_events.id",
            name="fk_match_forks_branch_event_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    branch_event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: Solari snapshot backing this fork; NULL until the rebuild finishes.
    solari_snapshot_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    #: Each agent's conversation cut at the branch point, stored so a fork is
    #: self-contained. NULL for rows recorded before conversations were kept.
    prisoner_messages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    warden_messages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
