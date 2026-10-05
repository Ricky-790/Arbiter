"""`matches` table: one Prisoner-vs-Warden match."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

#: Allowed ``status`` values (plain VARCHAR until a stricter type is asked for).
MATCH_STATUSES = (
    "queued",
    "pending",
    "starting",
    "running",
    "completed",
    "failed",
    "cancelled",
)

#: Statuses a match can no longer leave -- it is over, one way or another.
#: Only these can be forked: a match still being hosted is writing its own
#: history, so a fork of it would not resume from the point it claims to.
MATCH_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

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
    parent_match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "matches.id",
            name="fk_matches_parent_match_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    branch_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "match_events.id",
            name="fk_matches_branch_event_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
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

    #: End-of-match summary per side, written once by the Engine as the match
    #: closes. ``None`` until then, and for matches recorded before the column
    #: existed. JSONB rather than columns because the reviewer is expected to
    #: want more counters over time, and this is a snapshot, not a query key:
    #:
    #:     {"credits": int, "tool_calls": int}
    #:
    #: ``credits`` is what the side had left, ``tool_calls`` is how many actions
    #: it requested (rejected calls included, matching the ``tool_call`` rows in
    #: ``match_events``). Replayed calls from a fork rebuild are not counted.
    prisoner_stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warden_stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: The strategy each side was started with, keyed by side:
    #:
    #:     {"prisoner": str, "warden": str}
    #:
    #: Written once when the match is queued, from the operator's tips or from
    #: the library strategy a side was started from. The self-improvement loop
    #: reads it back when it promotes a finished match's strategy into the
    #: ``strategies`` table. ``NULL`` when neither side was given one, and a
    #: side with no strategy is simply absent from the object.
    strategy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: The ``strategies.id`` each side ran, keyed by side:
    #:
    #:     {"prisoner": "<uuid>", "warden": "<uuid>"}
    #:
    #: Set at queue time when a side was started from a saved strategy, and
    #: written back onto a match by ``save-strategy`` when one is promoted out
    #: of it. Both directions land here so a saved strategy can be traced to
    #: every match that ran it. The text alone cannot do that: it is copied onto
    #: each match, so two matches sharing wording are not otherwise related.
    #:
    #: Held as strings because it lives inside JSONB, and keyed by side because
    #: one match can carry a strategy for each. A side with no library strategy
    #: is absent rather than null.
    strategy_id: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    challenge: Mapped["Challenge"] = relationship(
        "Challenge", back_populates="matches", lazy="selectin"
    )
    events: Mapped[list["MatchEvent"]] = relationship(
        "MatchEvent",
        back_populates="match",
        foreign_keys="MatchEvent.match_id",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MatchEvent.timestamp",
    )
