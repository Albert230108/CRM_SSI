"""add tenant status filter preference to users

Revision ID: 0029_add_tenant_status_filter_to_users
Revises: 0028_add_tenant_email_addresses
Create Date: 2026-07-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0029_add_tenant_status_filter_to_users"
down_revision = "0028_add_tenant_email_addresses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("tenant_status_filter", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "tenant_status_filter")
