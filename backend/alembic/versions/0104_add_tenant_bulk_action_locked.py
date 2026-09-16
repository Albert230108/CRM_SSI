"""add tenants.bulk_action_locked to exclude a tenant from AI-settings bulk actions

Revision ID: 0104_add_tenant_bulk_action_locked
Revises: 0103_fix_ai_auto_draft_execution_status_backfill
Create Date: 2026-09-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0104_add_tenant_bulk_action_locked"
down_revision = "0103_fix_ai_auto_draft_execution_status_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defaults to false via the server default, so every existing and future tenant starts
    # unlocked and no creation site (import, manual create, Beds24 sync/webhook) needs to set it.
    op.add_column(
        "tenants",
        sa.Column("bulk_action_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("tenants", "bulk_action_locked")
