"""Add challenges.flag

The Engine needs the challenge flag (``ChallengeSpec.flag``) to build the
sandbox environment. The `challenges` table previously had nowhere to store it,
so the worker could not start a real match from a persisted challenge.

Revision ID: a1f2c3d4e5b6
Revises: bbea53e69bb7
Create Date: 2026-09-18 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1f2c3d4e5b6'
down_revision: Union[str, Sequence[str], None] = 'bbea53e69bb7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing rows get an empty flag via the server default; the default is
    # then dropped so future inserts must supply the flag explicitly.
    op.add_column(
        'challenges',
        sa.Column('flag', sa.Text(), nullable=False, server_default=''),
    )
    op.alter_column('challenges', 'flag', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('challenges', 'flag')
