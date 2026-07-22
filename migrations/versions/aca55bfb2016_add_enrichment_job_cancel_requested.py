"""add enrichment_jobs cancel_requested

Revision ID: aca55bfb2016
Revises: 93742b603778
Create Date: 2026-07-20 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aca55bfb2016'
down_revision: Union[str, Sequence[str], None] = '93742b603778'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('enrichment_jobs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('enrichment_jobs', schema=None) as batch_op:
        batch_op.drop_column('cancel_requested')
