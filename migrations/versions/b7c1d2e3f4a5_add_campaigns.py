"""add campaigns

Revision ID: b7c1d2e3f4a5
Revises: 3f9b145655c1
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c1d2e3f4a5'
down_revision: Union[str, Sequence[str], None] = '3f9b145655c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'campaigns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'campaign_schools',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('stage_at_move', sa.String(), nullable=False),
        sa.Column('added_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('campaign_schools', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_campaign_schools_campaign_id'), ['campaign_id'], unique=False)
        # Unique across ALL campaigns -- one school, one campaign, ever.
        batch_op.create_index(batch_op.f('ix_campaign_schools_school_id'), ['school_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('campaign_schools', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_campaign_schools_school_id'))
        batch_op.drop_index(batch_op.f('ix_campaign_schools_campaign_id'))
    op.drop_table('campaign_schools')
    op.drop_table('campaigns')
