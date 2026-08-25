"""add action writer role

Revision ID: 0061_add_action_writer_role
Revises: 0060_add_redo_request_log_processing
Create Date: 2026-08-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0061_add_action_writer_role"
down_revision = "0060_add_redo_request_log_processing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_writer_triggers",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email_thread_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("whatsapp_endpoint_id", sa.Integer(), sa.ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "channel", name="uq_action_writer_triggers_tenant_channel"),
    )
    op.create_index(op.f("ix_action_writer_triggers_tenant_id"), "action_writer_triggers", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_action_writer_triggers_trigger_at"), "action_writer_triggers", ["trigger_at"], unique=False)

    op.add_column(
        "tenant_ai_settings",
        sa.Column("action_writer_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tenant_ai_settings",
        sa.Column("action_writer_profile_id", sa.Integer(), sa.ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_ai_settings", "action_writer_profile_id")
    op.drop_column("tenant_ai_settings", "action_writer_enabled")

    op.drop_index(op.f("ix_action_writer_triggers_trigger_at"), table_name="action_writer_triggers")
    op.drop_index(op.f("ix_action_writer_triggers_tenant_id"), table_name="action_writer_triggers")
    op.drop_table("action_writer_triggers")
