"""Add schools.enrichment_issue -- where the last enrichment stopped short.

Revision ID: b7e4a91c2d55
Revises: c9d3e4f5a6b7
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e4a91c2d55"
down_revision = "c9d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("enrichment_issue", sa.String(), nullable=True))
    op.create_index("ix_schools_enrichment_issue", "schools", ["enrichment_issue"])


def downgrade() -> None:
    op.drop_index("ix_schools_enrichment_issue", table_name="schools")
    op.drop_column("schools", "enrichment_issue")
