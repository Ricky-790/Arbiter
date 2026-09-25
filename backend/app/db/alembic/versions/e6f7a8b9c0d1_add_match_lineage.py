"""Add match lineage columns.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-24 19:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("parent_match_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "matches",
        sa.Column("branch_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_matches_parent_match_id"),
        "matches",
        ["parent_match_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matches_branch_event_id"),
        "matches",
        ["branch_event_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_matches_parent_match_id",
        "matches",
        "matches",
        ["parent_match_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_matches_branch_event_id",
        "matches",
        "match_events",
        ["branch_event_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_matches_branch_event_id", "matches", type_="foreignkey")
    op.drop_constraint("fk_matches_parent_match_id", "matches", type_="foreignkey")
    op.drop_index(op.f("ix_matches_branch_event_id"), table_name="matches")
    op.drop_index(op.f("ix_matches_parent_match_id"), table_name="matches")
    op.drop_column("matches", "branch_event_id")
    op.drop_column("matches", "parent_match_id")
