"""add tenant brain entries, history, trigger queue, and settings

Revision ID: 0051_add_tenant_brain
Revises: 0050_add_ai_auto_draft_quoted_context
Create Date: 2026-08-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0051_add_tenant_brain"
down_revision = "0050_add_ai_auto_draft_quoted_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_brain_entries",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_tenant_brain_entries_tenant_id"), "tenant_brain_entries", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_brain_entries_created_at"), "tenant_brain_entries", ["created_at"], unique=False)

    op.create_table(
        "tenant_brain_entry_history",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("tenant_brain_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_tenant_brain_entry_history_tenant_id"), "tenant_brain_entry_history", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_brain_entry_history_entry_id"), "tenant_brain_entry_history", ["entry_id"], unique=False)
    op.create_index(op.f("ix_tenant_brain_entry_history_changed_at"), "tenant_brain_entry_history", ["changed_at"], unique=False)

    op.create_table(
        "tenant_brain_triggers",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email_thread_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("whatsapp_endpoint_id", sa.Integer(), sa.ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "channel", name="uq_tenant_brain_triggers_tenant_channel"),
    )
    op.create_index(op.f("ix_tenant_brain_triggers_tenant_id"), "tenant_brain_triggers", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_brain_triggers_trigger_at"), "tenant_brain_triggers", ["trigger_at"], unique=False)

    op.add_column(
        "tenant_ai_settings",
        sa.Column("brain_writer_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tenant_ai_settings",
        sa.Column("brain_writer_profile_id", sa.Integer(), sa.ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_ai_settings", "brain_writer_profile_id")
    op.drop_column("tenant_ai_settings", "brain_writer_enabled")

    op.drop_index(op.f("ix_tenant_brain_triggers_trigger_at"), table_name="tenant_brain_triggers")
    op.drop_index(op.f("ix_tenant_brain_triggers_tenant_id"), table_name="tenant_brain_triggers")
    op.drop_table("tenant_brain_triggers")

    op.drop_index(op.f("ix_tenant_brain_entry_history_changed_at"), table_name="tenant_brain_entry_history")
    op.drop_index(op.f("ix_tenant_brain_entry_history_entry_id"), table_name="tenant_brain_entry_history")
    op.drop_index(op.f("ix_tenant_brain_entry_history_tenant_id"), table_name="tenant_brain_entry_history")
    op.drop_table("tenant_brain_entry_history")

    op.drop_index(op.f("ix_tenant_brain_entries_created_at"), table_name="tenant_brain_entries")
    op.drop_index(op.f("ix_tenant_brain_entries_tenant_id"), table_name="tenant_brain_entries")
    op.drop_table("tenant_brain_entries")
