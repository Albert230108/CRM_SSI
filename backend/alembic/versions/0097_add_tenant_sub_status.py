"""add tenants.sub_status for Beds24 sub-status sync

Revision ID: 0097_add_tenant_sub_status
Revises: 0096_add_webhook_auto_run
Create Date: 2026-09-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0097_add_tenant_sub_status"
down_revision = "0096_add_webhook_auto_run"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("sub_status", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "sub_status")
