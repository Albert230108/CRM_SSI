"""add device_tokens, notification push trigger, and notifications.push_dispatched_at

Revision ID: 0087_add_device_tokens_and_push
Revises: 0086_add_redo_previous_draft_text
Create Date: 2026-08-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0087_add_device_tokens_and_push"
down_revision = "0086_add_redo_previous_draft_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token", name="uq_device_tokens_token"),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])

    op.create_table(
        "notification_push_triggers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_notification_push_triggers_trigger_at", "notification_push_triggers", ["trigger_at"]
    )

    op.add_column(
        "notifications", sa.Column("push_dispatched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_notifications_push_dispatched_at", "notifications", ["push_dispatched_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_push_dispatched_at", table_name="notifications")
    op.drop_column("notifications", "push_dispatched_at")
    op.drop_index(
        "ix_notification_push_triggers_trigger_at", table_name="notification_push_triggers"
    )
    op.drop_table("notification_push_triggers")
    op.drop_index("ix_device_tokens_user_id", table_name="device_tokens")
    op.drop_table("device_tokens")
