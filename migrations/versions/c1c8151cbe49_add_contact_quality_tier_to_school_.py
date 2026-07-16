"""add contact_quality tier to school_contacts

Revision ID: c1c8151cbe49
Revises: f8872f5a8749
Create Date: 2026-07-14 14:44:48.956852

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1c8151cbe49'
down_revision: Union[str, Sequence[str], None] = 'f8872f5a8749'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('school_contacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('contact_quality', sa.String(), nullable=True))

    # Derive the 3-tier value fresh from the stored person_name/email
    # columns themselves -- more correct than reverse-engineering it from
    # the old boolean, since that boolean couldn't distinguish "no person
    # found at all" from "person found but no email" (both were simply
    # False before; this backfill tells them apart as failed vs. partial).
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE school_contacts
        SET contact_quality = CASE
            WHEN person_name IS NOT NULL AND email IS NOT NULL THEN 'verified'
            WHEN person_name IS NOT NULL THEN 'partial'
            ELSE 'failed'
        END
    """))

    with op.batch_alter_table('school_contacts', schema=None) as batch_op:
        batch_op.alter_column('contact_quality', nullable=False)
        batch_op.drop_column('verified')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('school_contacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('verified', sa.BOOLEAN(), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE school_contacts
        SET verified = (contact_quality = 'verified')
    """))

    with op.batch_alter_table('school_contacts', schema=None) as batch_op:
        batch_op.alter_column('verified', nullable=False)
        batch_op.drop_column('contact_quality')
