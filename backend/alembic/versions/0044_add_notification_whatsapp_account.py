"""add notification whatsapp external account id

Revision ID: 0044_add_notification_whatsapp_account
Revises: 0043_add_notification_whatsapp_alerts
Create Date: 2026-08-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0044_add_notification_whatsapp_account"
down_revision = "0043_add_notification_whatsapp_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_settings",
        sa.Column("notification_whatsapp_external_account_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admin_settings", "notification_whatsapp_external_account_id")
