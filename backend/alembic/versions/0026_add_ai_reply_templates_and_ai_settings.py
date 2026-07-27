"""add ai reply templates, tenant ai settings, and auto-draft scheduling tables

Revision ID: 0026_add_ai_reply_templates_and_ai_settings
Revises: 0025_add_admin_settings_and_email_templates
Create Date: 2026-07-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_add_ai_reply_templates_and_ai_settings"
down_revision = "0025_add_admin_settings_and_email_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_reply_templates",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("include_history", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("history_message_limit", sa.Integer(), nullable=True),
        sa.Column("include_beds24", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("include_payments", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "tenant_ai_template_links",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("ai_reply_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "template_id", name="uq_tenant_ai_template_links_tenant_template"),
    )
    op.create_index(op.f("ix_tenant_ai_template_links_tenant_id"), "tenant_ai_template_links", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_ai_template_links_template_id"), "tenant_ai_template_links", ["template_id"], unique=False)

    op.create_table(
        "tenant_ai_settings",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("default_email_template_id", sa.Integer(), sa.ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("default_whatsapp_template_id", sa.Integer(), sa.ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("auto_draft_email", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_draft_whatsapp", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_send_email", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_send_whatsapp", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_ai_settings_tenant_id"),
    )
    op.create_index(op.f("ix_tenant_ai_settings_tenant_id"), "tenant_ai_settings", ["tenant_id"], unique=False)

    op.create_table(
        "ai_auto_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email_thread_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("whatsapp_endpoint_id", sa.Integer(), sa.ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("generated_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("scheduled_send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_communication_id", sa.Integer(), sa.ForeignKey("communications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_ai_auto_drafts_tenant_id"), "ai_auto_drafts", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_ai_auto_drafts_channel"), "ai_auto_drafts", ["channel"], unique=False)
    op.create_index(op.f("ix_ai_auto_drafts_status"), "ai_auto_drafts", ["status"], unique=False)
    op.create_index("ix_ai_auto_drafts_tenant_channel_status", "ai_auto_drafts", ["tenant_id", "channel", "status"], unique=False)

    op.create_table(
        "ai_auto_draft_triggers",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email_thread_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("whatsapp_endpoint_id", sa.Integer(), sa.ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "channel", name="uq_ai_auto_draft_triggers_tenant_channel"),
    )
    op.create_index(op.f("ix_ai_auto_draft_triggers_tenant_id"), "ai_auto_draft_triggers", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_ai_auto_draft_triggers_trigger_at"), "ai_auto_draft_triggers", ["trigger_at"], unique=False)

    op.add_column("communications", sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    op.add_column("admin_settings", sa.Column("ai_draft_debounce_seconds", sa.Integer(), nullable=False, server_default="120"))
    op.add_column("admin_settings", sa.Column("ai_auto_send_delay_seconds", sa.Integer(), nullable=False, server_default="300"))


def downgrade() -> None:
    op.drop_column("admin_settings", "ai_auto_send_delay_seconds")
    op.drop_column("admin_settings", "ai_draft_debounce_seconds")

    op.drop_column("communications", "ai_generated")

    op.drop_index(op.f("ix_ai_auto_draft_triggers_trigger_at"), table_name="ai_auto_draft_triggers")
    op.drop_index(op.f("ix_ai_auto_draft_triggers_tenant_id"), table_name="ai_auto_draft_triggers")
    op.drop_table("ai_auto_draft_triggers")

    op.drop_index("ix_ai_auto_drafts_tenant_channel_status", table_name="ai_auto_drafts")
    op.drop_index(op.f("ix_ai_auto_drafts_status"), table_name="ai_auto_drafts")
    op.drop_index(op.f("ix_ai_auto_drafts_channel"), table_name="ai_auto_drafts")
    op.drop_index(op.f("ix_ai_auto_drafts_tenant_id"), table_name="ai_auto_drafts")
    op.drop_table("ai_auto_drafts")

    op.drop_index(op.f("ix_tenant_ai_settings_tenant_id"), table_name="tenant_ai_settings")
    op.drop_table("tenant_ai_settings")

    op.drop_index(op.f("ix_tenant_ai_template_links_template_id"), table_name="tenant_ai_template_links")
    op.drop_index(op.f("ix_tenant_ai_template_links_tenant_id"), table_name="tenant_ai_template_links")
    op.drop_table("tenant_ai_template_links")

    op.drop_table("ai_reply_templates")
