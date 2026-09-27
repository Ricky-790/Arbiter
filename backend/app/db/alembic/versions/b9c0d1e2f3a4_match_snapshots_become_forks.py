"""Turn the snapshot index into a saved-fork table.

A fork is a saved point a match can later be started from, and a Solari
snapshot is what backs it, so the old ``match_snapshots`` index becomes
``match_forks``. Data is preserved by renaming rather than recreating.

Revision ID: b9c0d1e2f3a4
Revises: f7a8b9c0d1e2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("match_snapshots", "match_forks")
    op.alter_column("match_forks", "match_id", new_column_name="parent_match_id")
    # A fork exists before its snapshot does.
    op.alter_column("match_forks", "solari_snapshot_id", nullable=True)

    op.execute(
        "ALTER INDEX ix_match_snapshots_match_id "
        "RENAME TO ix_match_forks_parent_match_id"
    )
    op.execute(
        "ALTER INDEX ix_match_snapshots_branch_event_id "
        "RENAME TO ix_match_forks_branch_event_id"
    )
    op.execute(
        "ALTER TABLE match_forks RENAME CONSTRAINT "
        "uq_match_snapshots_match_branch TO uq_match_forks_parent_branch"
    )
    op.execute(
        "ALTER TABLE match_forks RENAME CONSTRAINT "
        "fk_match_snapshots_match_id TO fk_match_forks_parent_match_id"
    )
    op.execute(
        "ALTER TABLE match_forks RENAME CONSTRAINT "
        "fk_match_snapshots_branch_event_id TO fk_match_forks_branch_event_id"
    )

    # Every pre-existing row already had its snapshot built.
    op.add_column(
        "match_forks",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="ready",
        ),
    )
    op.add_column(
        "match_forks",
        sa.Column("prisoner_messages", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "match_forks",
        sa.Column("warden_messages", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        op.f("ix_match_forks_status"), "match_forks", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_match_forks_created_at"),
        "match_forks",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_match_forks_created_at"), table_name="match_forks")
    op.drop_index(op.f("ix_match_forks_status"), table_name="match_forks")
    op.drop_column("match_forks", "warden_messages")
    op.drop_column("match_forks", "prisoner_messages")
    op.drop_column("match_forks", "status")

    op.execute(
        "ALTER TABLE match_forks RENAME CONSTRAINT "
        "fk_match_forks_branch_event_id TO fk_match_snapshots_branch_event_id"
    )
    op.execute(
        "ALTER TABLE match_forks RENAME CONSTRAINT "
        "fk_match_forks_parent_match_id TO fk_match_snapshots_match_id"
    )
    op.execute(
        "ALTER TABLE match_forks RENAME CONSTRAINT "
        "uq_match_forks_parent_branch TO uq_match_snapshots_match_branch"
    )
    op.execute(
        "ALTER INDEX ix_match_forks_branch_event_id "
        "RENAME TO ix_match_snapshots_branch_event_id"
    )
    op.execute(
        "ALTER INDEX ix_match_forks_parent_match_id "
        "RENAME TO ix_match_snapshots_match_id"
    )

    op.alter_column("match_forks", "solari_snapshot_id", nullable=False)
    op.alter_column("match_forks", "parent_match_id", new_column_name="match_id")
    op.rename_table("match_forks", "match_snapshots")
