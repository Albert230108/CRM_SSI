"""add memory qa messages

Revision ID: 0058_add_memory_qa_messages
Revises: 0057_add_redo_log_and_memory_suggestions
Create Date: 2026-08-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0058_add_memory_qa_messages"
down_revision = "0057_add_redo_log_and_memory_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_qa_messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("asked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_memory_qa_messages_tenant_id"), "memory_qa_messages", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_memory_qa_messages_created_at"), "memory_qa_messages", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_memory_qa_messages_created_at"), table_name="memory_qa_messages")
    op.drop_index(op.f("ix_memory_qa_messages_tenant_id"), table_name="memory_qa_messages")
    op.drop_table("memory_qa_messages")
