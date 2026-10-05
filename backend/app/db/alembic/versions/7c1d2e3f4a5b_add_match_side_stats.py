"""Add end-of-match side stats to `matches`.

One nullable JSONB column per side, written by the Engine as the match closes.
The reviewer reads them; nothing else queries inside them.

Revision ID: 7c1d2e3f4a5b
Revises: 5e84595292f7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c1d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "5e84595292f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the per-side match summaries."""
    op.add_column(
        "matches", sa.Column("prisoner_stats", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "matches", sa.Column("warden_stats", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    """Drop the per-side match summaries."""
    op.drop_column("matches", "warden_stats")
    op.drop_column("matches", "prisoner_stats")
