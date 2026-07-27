"""add composite index on schools is_active, level

Revision ID: 3c7524787d34
Revises: 3f9b145655b8
Create Date: 2026-07-22 15:07:35.456716

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c7524787d34'
down_revision: Union[str, Sequence[str], None] = '3f9b145655b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.create_index('ix_schools_is_active_level', ['is_active', 'level'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_index('ix_schools_is_active_level')
