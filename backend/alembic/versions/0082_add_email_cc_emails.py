"""add cc emails to gmail conversations and communications

Revision ID: 0082_add_email_cc_emails
Revises: 0081_add_redo_request_reviewed
Create Date: 2026-08-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0082_add_email_cc_emails"
down_revision = "0081_add_redo_request_reviewed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_messages", sa.Column("cc_emails", sa.Text(), nullable=True))
    op.add_column("communications", sa.Column("cc_emails", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("communications", "cc_emails")
    op.drop_column("conversation_messages", "cc_emails")
