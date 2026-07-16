"""add school specialty

Revision ID: 06e5bd09195e
Revises: 2598dccc0722
Create Date: 2026-07-15 16:36:07.972199

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '06e5bd09195e'
down_revision: Union[str, Sequence[str], None] = '2598dccc0722'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.add_column(sa.Column('specialty', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_column('specialty')
