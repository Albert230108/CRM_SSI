"""add tenant_ai_settings.webhook_auto_run_enabled (default on)

Revision ID: 0096_add_webhook_auto_run
Revises: 0095_add_finance_status
Create Date: 2026-09-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0096_add_webhook_auto_run"
down_revision = "0095_add_finance_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Default true so existing and new tenants opt in; the brain/action-writer enables stay the
    # authoritative gate for whether anything actually runs.
    op.add_column(
        "tenant_ai_settings",
        sa.Column("webhook_auto_run_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("tenant_ai_settings", "webhook_auto_run_enabled")
