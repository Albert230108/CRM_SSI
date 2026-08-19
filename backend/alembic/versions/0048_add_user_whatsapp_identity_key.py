"""add users.whatsapp_identity_key

Revision ID: 0048_add_user_whatsapp_identity_key
Revises: 0047_add_ai_auto_draft_approval_requests
Create Date: 2026-08-19 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0048_add_user_whatsapp_identity_key"
down_revision = "0047_add_ai_auto_draft_approval_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("whatsapp_identity_key", sa.String(length=255), nullable=True))
    op.create_index("ix_users_whatsapp_identity_key", "users", ["whatsapp_identity_key"])


def downgrade() -> None:
    op.drop_index("ix_users_whatsapp_identity_key", table_name="users")
    op.drop_column("users", "whatsapp_identity_key")
