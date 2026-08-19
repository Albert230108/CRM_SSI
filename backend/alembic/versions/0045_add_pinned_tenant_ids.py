"""add pinned tenant ids to users

Revision ID: 0045_add_pinned_tenant_ids
Revises: 0044_add_notification_whatsapp_account
Create Date: 2026-08-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0045_add_pinned_tenant_ids"
down_revision = "0044_add_notification_whatsapp_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pinned_tenant_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "pinned_tenant_ids")
