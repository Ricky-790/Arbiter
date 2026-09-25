"""`match_events` table: persistent history of match actions and events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

#: Allowed ``actor`` values (plain VARCHAR until a stricter type is asked for).
EVENT_ACTORS = ("prisoner", "warden", "system")

#: Recorded ``event_type`` values; more may be added later without migration
#: pain because the column is plain VARCHAR.
EVENT_TYPES = (
    "chat",
    "tool_call",
    "sandbox_event",
    "match_started",
    "match_finished",
    "trap_triggered",
    "agent_retry",
    "agent_error",
    "agent_unavailable",
)


class MatchEvent(Base):
    """One persisted match action/event.

    ``action``/``result`` are JSONB because chat and tool-call payloads differ.
    """

    __tablename__ = "match_events"
    __table_args__ = (
        Index("ix_match_events_match_time", "match_id", "timestamp"),
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
    actor: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    action: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    match: Mapped["Match"] = relationship(
        "Match",
        back_populates="events",
        foreign_keys="MatchEvent.match_id",
        lazy="selectin",
    )
