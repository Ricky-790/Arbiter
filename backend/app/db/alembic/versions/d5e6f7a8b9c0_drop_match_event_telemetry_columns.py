"""Drop unused telemetry columns from match_events

``match_events`` is the lightweight, timestamped action log (actor, event type,
action, result). Token counts and latency are provider telemetry that belongs
in Logfire, so the four data columns are dead weight here.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-20 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("match_events", "input_tokens")
    op.drop_column("match_events", "output_tokens")
    op.drop_column("match_events", "total_tokens")
    op.drop_column("match_events", "latency_ms")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "match_events", sa.Column("latency_ms", sa.Float(), nullable=True)
    )
    op.add_column(
        "match_events", sa.Column("total_tokens", sa.Integer(), nullable=True)
    )
    op.add_column(
        "match_events", sa.Column("output_tokens", sa.Integer(), nullable=True)
    )
    op.add_column(
        "match_events", sa.Column("input_tokens", sa.Integer(), nullable=True)
    )
