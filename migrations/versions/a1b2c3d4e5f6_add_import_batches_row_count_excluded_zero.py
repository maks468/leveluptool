"""add import_batches row_count_excluded_zero_students

Revision ID: a1b2c3d4e5f6
Revises: efc3f9914b9d
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'efc3f9914b9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('import_batches', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('row_count_excluded_zero_students', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('import_batches', schema=None) as batch_op:
        batch_op.drop_column('row_count_excluded_zero_students')
