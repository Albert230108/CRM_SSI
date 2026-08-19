"""add notification whatsapp alerts

Revision ID: 0043_add_notification_whatsapp_alerts
Revises: 0042_add_brain_section_color
Create Date: 2026-08-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0043_add_notification_whatsapp_alerts"
down_revision = "0042_add_brain_section_color"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("whatsapp_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.add_column(
        "admin_settings",
        sa.Column("notification_whatsapp_debounce_seconds", sa.Integer(), nullable=False, server_default="120"),
    )

    op.add_column(
        "notifications",
        sa.Column("whatsapp_dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_notifications_whatsapp_dispatched_at"), "notifications", ["whatsapp_dispatched_at"], unique=False
    )

    op.create_table(
        "notification_whatsapp_triggers",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        op.f("ix_notification_whatsapp_triggers_trigger_at"),
        "notification_whatsapp_triggers",
        ["trigger_at"],
        unique=False,
    )

    op.create_table(
        "notification_whatsapp_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(length=100), nullable=False),
        sa.Column("notification_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        op.f("ix_notification_whatsapp_deliveries_user_id"),
        "notification_whatsapp_deliveries",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_whatsapp_deliveries_user_id"), table_name="notification_whatsapp_deliveries")
    op.drop_table("notification_whatsapp_deliveries")

    op.drop_index(op.f("ix_notification_whatsapp_triggers_trigger_at"), table_name="notification_whatsapp_triggers")
    op.drop_table("notification_whatsapp_triggers")

    op.drop_index(op.f("ix_notifications_whatsapp_dispatched_at"), table_name="notifications")
    op.drop_column("notifications", "whatsapp_dispatched_at")

    op.drop_column("admin_settings", "notification_whatsapp_debounce_seconds")

    op.drop_column("users", "whatsapp_notifications_enabled")
