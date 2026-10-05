"""`strategies` table: the library the self-improvement loop grows.

A strategy is a reusable, reviewable approach a side can be started with. It is
promoted out of a *finished* match -- never authored against the table directly
-- so every row can be traced back to the match that produced it and the
challenge it was played on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

#: The sides a strategy can belong to. Mirrors ``AgentType`` / ``app.secrets``
#: without importing either: a strategy is a database concept, and the ORM layer
#: does not depend on the runtime.
STRATEGY_USERS = ("prisoner", "warden")


class Strategy(Base):
    """One saved strategy, promoted from one side of one match.

    ``match_id`` and ``user`` together are unique: a match has at most one
    strategy per side, so re-promoting the same side is a no-op rather than a
    duplicate row. ``challenge_id`` is denormalised from the match because a
    strategy is only meaningful against the challenge it was played on, and
    scoping the library by challenge should not need a join.

    ``origin_strat_id`` is the strategy this one was evolved from, when the
    match itself was started from a library strategy. It is a self-reference, so
    lineage survives deleting an ancestor -- the pointer is cleared rather than
    taking the descendant with it.
    """

    __tablename__ = "strategies"
    __table_args__ = (
        UniqueConstraint("match_id", "user", name="uq_strategies_match_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: The match this strategy was promoted from.
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "matches.id",
            name="fk_strategies_match_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("challenges.id", name="fk_strategies_challenge_id"),
        nullable=False,
        index=True,
    )
    #: Which side the strategy is for: ``prisoner`` or ``warden``.
    user: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: A short label for lists and pickers, derived from the strategy text.
    one_line_description: Mapped[str] = mapped_column(Text, nullable=False)
    #: The strategy itself, exactly as the match ran it.
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    #: The strategy this one evolved from, when there was one.
    origin_strat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "strategies.id",
            name="fk_strategies_origin_strat_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
