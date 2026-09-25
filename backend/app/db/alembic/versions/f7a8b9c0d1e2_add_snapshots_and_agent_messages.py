"""Add fork snapshots and agent message history.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-25 22:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "match_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "branch_event_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("solari_snapshot_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name="fk_match_snapshots_match_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["branch_event_id"],
            ["match_events.id"],
            name="fk_match_snapshots_branch_event_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_id",
            "branch_event_id",
            name="uq_match_snapshots_match_branch",
        ),
    )
    op.create_index(
        op.f("ix_match_snapshots_match_id"),
        "match_snapshots",
        ["match_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_match_snapshots_branch_event_id"),
        "match_snapshots",
        ["branch_event_id"],
        unique=False,
    )

    op.create_table(
        "match_agent_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name="fk_match_agent_messages_match_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_id",
            "actor",
            name="uq_match_agent_messages_match_actor",
        ),
    )
    op.create_index(
        op.f("ix_match_agent_messages_match_id"),
        "match_agent_messages",
        ["match_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_match_agent_messages_match_id"),
        table_name="match_agent_messages",
    )
    op.drop_table("match_agent_messages")
    op.drop_index(
        op.f("ix_match_snapshots_branch_event_id"),
        table_name="match_snapshots",
    )
    op.drop_index(
        op.f("ix_match_snapshots_match_id"),
        table_name="match_snapshots",
    )
    op.drop_table("match_snapshots")
