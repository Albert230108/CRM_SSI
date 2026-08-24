"""add redo request logs and memory suggestions

Revision ID: 0057_add_redo_log_and_memory_suggestions
Revises: 0056_add_working_memory_rules
Create Date: 2026-08-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0057_add_redo_log_and_memory_suggestions"
down_revision = "0056_add_working_memory_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "redo_request_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("ai_auto_draft_id", sa.Integer(), sa.ForeignKey("ai_auto_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("what", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_redo_request_logs_ai_auto_draft_id"), "redo_request_logs", ["ai_auto_draft_id"], unique=False)
    op.create_index(op.f("ix_redo_request_logs_tenant_id"), "redo_request_logs", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_redo_request_logs_created_at"), "redo_request_logs", ["created_at"], unique=False)

    op.create_table(
        "memory_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("proposed_value", sa.JSON(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column(
            "source_redo_log_id", sa.Integer(), sa.ForeignKey("redo_request_logs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_memory_suggestions_tenant_id"), "memory_suggestions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_memory_suggestions_created_at"), "memory_suggestions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_memory_suggestions_created_at"), table_name="memory_suggestions")
    op.drop_index(op.f("ix_memory_suggestions_tenant_id"), table_name="memory_suggestions")
    op.drop_table("memory_suggestions")

    op.drop_index(op.f("ix_redo_request_logs_created_at"), table_name="redo_request_logs")
    op.drop_index(op.f("ix_redo_request_logs_tenant_id"), table_name="redo_request_logs")
    op.drop_index(op.f("ix_redo_request_logs_ai_auto_draft_id"), table_name="redo_request_logs")
    op.drop_table("redo_request_logs")
