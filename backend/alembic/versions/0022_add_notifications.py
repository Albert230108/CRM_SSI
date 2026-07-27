"""add notifications and notification_reads

Revision ID: 0022_add_notifications
Revises: 0021_gmail_watch_expiration
Create Date: 2026-07-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_add_notifications"
down_revision = "0021_gmail_watch_expiration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("tenant_name", sa.String(length=255), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False, server_default="inbound"),
        sa.Column("preview", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_notifications_id"), "notifications", ["id"], unique=False)
    op.create_index(op.f("ix_notifications_tenant_id"), "notifications", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)

    op.create_table(
        "notification_reads",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_notification_user"),
    )
    op.create_index(op.f("ix_notification_reads_id"), "notification_reads", ["id"], unique=False)
    op.create_index(op.f("ix_notification_reads_notification_id"), "notification_reads", ["notification_id"], unique=False)
    op.create_index(op.f("ix_notification_reads_user_id"), "notification_reads", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_reads_user_id"), table_name="notification_reads")
    op.drop_index(op.f("ix_notification_reads_notification_id"), table_name="notification_reads")
    op.drop_index(op.f("ix_notification_reads_id"), table_name="notification_reads")
    op.drop_table("notification_reads")

    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_tenant_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_id"), table_name="notifications")
    op.drop_table("notifications")
