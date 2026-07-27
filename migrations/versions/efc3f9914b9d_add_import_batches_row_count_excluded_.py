"""add import_batches row_count_excluded_special_needs

Revision ID: efc3f9914b9d
Revises: 3c7524787d34
Create Date: 2026-07-24 11:34:31.879633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'efc3f9914b9d'
down_revision: Union[str, Sequence[str], None] = '3c7524787d34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('import_batches', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('row_count_excluded_special_needs', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('import_batches', schema=None) as batch_op:
        batch_op.drop_column('row_count_excluded_special_needs')
