"""add school_contacts confidence evidence extraction_method, enrichment_jobs error_message

Revision ID: 3f9b145655b8
Revises: aca55bfb2016
Create Date: 2026-07-22 12:15:22.822504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f9b145655b8'
down_revision: Union[str, Sequence[str], None] = 'aca55bfb2016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('enrichment_jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('error_message', sa.String(), nullable=True))

    with op.batch_alter_table('school_contacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confidence', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('evidence', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('extraction_method', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('school_contacts', schema=None) as batch_op:
        batch_op.drop_column('extraction_method')
        batch_op.drop_column('evidence')
        batch_op.drop_column('confidence')

    with op.batch_alter_table('enrichment_jobs', schema=None) as batch_op:
        batch_op.drop_column('error_message')
