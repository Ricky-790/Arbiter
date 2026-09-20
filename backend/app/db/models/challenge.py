"""`challenges` table: developer-authored challenge scenarios."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Challenge(Base):
    """One developer-authored challenge scenario."""

    __tablename__ = "challenges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    win_condition: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    challenge_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    verification_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    #: The correct flag output, structured to match ``flag_structure``.
    flag: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    #: Expected shape of an agent submission: field name -> type name
    #: (e.g. ``{"value": "str"}``). Empty means "no shape constraint".
    flag_structure: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    #: Optional in-sandbox script that verifies a submission and prints a
    #: JSON verdict. When absent, the engine compares against ``flag``.
    verifier_script: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    sandbox_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    files: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    env_vars: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    setup_script: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    matches: Mapped[list["Match"]] = relationship(
        "Match",
        back_populates="challenge",
        lazy="selectin",
    )
