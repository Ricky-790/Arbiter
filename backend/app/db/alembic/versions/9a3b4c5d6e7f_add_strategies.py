"""Add the `strategies` library and the per-match strategy columns.

Creates the table the self-improvement loop promotes finished matches into, and
adds `matches.strategy` / `matches.strategy_id` -- both JSONB keyed by side,
because one match can carry a strategy for the Prisoner and the Warden at once.

Revision ID: 9a3b4c5d6e7f
Revises: 7c1d2e3f4a5b
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a3b4c5d6e7f"
down_revision: Union[str, Sequence[str], None] = "7c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the strategy columns and the strategies table."""
    op.add_column(
        "matches", sa.Column("strategy", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "matches", sa.Column("strategy_id", postgresql.JSONB(), nullable=True)
    )

    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("challenge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user", sa.String(length=16), nullable=False),
        sa.Column("one_line_description", sa.Text(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("origin_strat_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name="fk_strategies_match_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["challenges.id"],
            name="fk_strategies_challenge_id",
        ),
        sa.ForeignKeyConstraint(
            ["origin_strat_id"],
            ["strategies.id"],
            name="fk_strategies_origin_strat_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", "user", name="uq_strategies_match_user"),
    )
    op.create_index("ix_strategies_match_id", "strategies", ["match_id"])
    op.create_index("ix_strategies_challenge_id", "strategies", ["challenge_id"])
    op.create_index("ix_strategies_user", "strategies", ["user"])
    op.create_index(
        "ix_strategies_origin_strat_id", "strategies", ["origin_strat_id"]
    )
    op.create_index("ix_strategies_created_at", "strategies", ["created_at"])


def downgrade() -> None:
    """Drop the strategies table and the per-match strategy columns."""
    op.drop_index("ix_strategies_created_at", table_name="strategies")
    op.drop_index("ix_strategies_origin_strat_id", table_name="strategies")
    op.drop_index("ix_strategies_user", table_name="strategies")
    op.drop_index("ix_strategies_challenge_id", table_name="strategies")
    op.drop_index("ix_strategies_match_id", table_name="strategies")
    op.drop_table("strategies")
    op.drop_column("matches", "strategy_id")
    op.drop_column("matches", "strategy")
