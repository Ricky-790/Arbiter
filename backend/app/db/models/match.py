"""`matches` table: one Prisoner-vs-Warden match."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

#: Allowed ``status`` values (plain VARCHAR until a stricter type is asked for).
MATCH_STATUSES = (
    "pending",
    "starting",
    "running",
    "completed",
    "failed",
    "cancelled",
)

#: Allowed ``winner`` values; NULL until the match finishes.
MATCH_WINNERS = ("prisoner", "warden", "draw")


class Match(Base):
    """One Prisoner-vs-Warden match.

    ``win_condition`` snapshots the challenge's win condition at creation time.
    """

    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("challenges.id"),
        nullable=False,
        index=True,
    )
    prisoner_model: Mapped[str] = mapped_column(String(255), nullable=False)
    prisoner_provider: Mapped[str] = mapped_column(String(255), nullable=False)
    warden_model: Mapped[str] = mapped_column(String(255), nullable=False)
    warden_provider: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    winner: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    win_condition: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    challenge: Mapped["Challenge"] = relationship(
        "Challenge", back_populates="matches", lazy="selectin"
    )
    events: Mapped[list["MatchEvent"]] = relationship(
        "MatchEvent",
        back_populates="match",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MatchEvent.timestamp",
    )
