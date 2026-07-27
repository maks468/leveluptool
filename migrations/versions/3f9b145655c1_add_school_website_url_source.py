"""add school website_url_source

Revision ID: 3f9b145655c1
Revises: a1b2c3d4e5f6
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f9b145655c1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.add_column(sa.Column('website_url_source', sa.String(length=21), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_column('website_url_source')
