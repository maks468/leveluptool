"""add school name_disambiguator

Revision ID: 93742b603778
Revises: f8fc9980be36
Create Date: 2026-07-18 10:29:36.901607

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '93742b603778'
down_revision: Union[str, Sequence[str], None] = 'f8fc9980be36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name_disambiguator', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('schools', schema=None) as batch_op:
        batch_op.drop_column('name_disambiguator')
