"""add notifications.event_at

Revision ID: 0024_add_notification_event_at
Revises: 0023_add_tenant_conversation_links
Create Date: 2026-07-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_add_notification_event_at"
down_revision = "0023_add_tenant_conversation_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
    )
    # Backfill existing rows: created_at is the best available approximation for
    # notifications ingested before this column existed.
    op.execute("UPDATE notifications SET event_at = created_at WHERE event_at IS NULL")
    op.alter_column("notifications", "event_at", nullable=False, server_default=sa.text("now()"))
    op.create_index(op.f("ix_notifications_event_at"), "notifications", ["event_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_event_at"), table_name="notifications")
    op.drop_column("notifications", "event_at")
