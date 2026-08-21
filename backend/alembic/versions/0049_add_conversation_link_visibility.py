"""add tenant_conversation_links.is_visible and tenants.auto_add_shared_email_threads

Revision ID: 0049_add_conversation_link_visibility
Revises: 0048_add_user_whatsapp_identity_key
Create Date: 2026-08-21 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0049_add_conversation_link_visibility"
down_revision = "0048_add_user_whatsapp_identity_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_conversation_links",
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "tenants",
        sa.Column("auto_add_shared_email_threads", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("tenants", "auto_add_shared_email_threads")
    op.drop_column("tenant_conversation_links", "is_visible")
