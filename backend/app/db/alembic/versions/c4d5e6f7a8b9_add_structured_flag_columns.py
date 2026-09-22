"""Add structured flags to challenges

Different challenge types produce different flag shapes, so the expected
output is stored as JSON (``flag``) together with the shape an agent must
submit (``flag_structure``). An optional ``verifier_script`` lets a challenge
be judged by a script running inside the sandbox instead of a plain value
comparison.

Revision ID: c4d5e6f7a8b9
Revises: 3b00729adfbd
Create Date: 2026-09-20 09:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "3b00729adfbd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing rows are backfilled with the server default, which is then
    # dropped so future inserts must supply the value explicitly.
    op.add_column(
        "challenges",
        sa.Column(
            "flag",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "challenges",
        sa.Column(
            "flag_structure",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "challenges",
        sa.Column("verifier_script", sa.Text(), nullable=True),
    )
    op.alter_column("challenges", "flag", server_default=None)
    op.alter_column("challenges", "flag_structure", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("challenges", "verifier_script")
    op.drop_column("challenges", "flag_structure")
    op.drop_column("challenges", "flag")
