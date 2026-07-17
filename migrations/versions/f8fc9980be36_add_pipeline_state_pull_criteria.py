"""add pipeline_state pull_criteria

Revision ID: f8fc9980be36
Revises: 06e5bd09195e
Create Date: 2026-07-17 15:06:39.774667

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8fc9980be36'
down_revision: Union[str, Sequence[str], None] = '06e5bd09195e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('pipeline_state', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pull_criteria', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('pipeline_state', schema=None) as batch_op:
        batch_op.drop_column('pull_criteria')
