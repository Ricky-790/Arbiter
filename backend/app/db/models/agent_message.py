"""`match_agent_messages` table: persisted pydantic-ai conversation history."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MatchAgentMessages(Base):
    """One agent's conversation history, stored when its match finishes.

    Held in its own table rather than on ``matches`` because the payload is
    large and only ever read for one match at a time; keeping it off the
    ``matches`` row leaves the archive listing cheap.

    ``messages`` is a JSON-safe dump of pydantic-ai's ``all_messages()`` and is
    loadable back with ``ModelMessagesTypeAdapter.validate_python``.
    """

    __tablename__ = "match_agent_messages"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "actor", name="uq_match_agent_messages_match_actor"
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
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    messages: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
