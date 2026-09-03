"""add run qa messages

Revision ID: 0089_add_run_qa_messages
Revises: 0088_add_tenant_is_new
Create Date: 2026-09-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0089_add_run_qa_messages"
down_revision = "0088_add_tenant_is_new"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_qa_messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("agent_run_id", sa.Integer(), sa.ForeignKey("ai_agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qa_run_id", sa.Integer(), sa.ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("asked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_run_qa_messages_agent_run_id"), "run_qa_messages", ["agent_run_id"], unique=False)
    op.create_index(op.f("ix_run_qa_messages_qa_run_id"), "run_qa_messages", ["qa_run_id"], unique=False)
    op.create_index(op.f("ix_run_qa_messages_created_at"), "run_qa_messages", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_run_qa_messages_created_at"), table_name="run_qa_messages")
    op.drop_index(op.f("ix_run_qa_messages_qa_run_id"), table_name="run_qa_messages")
    op.drop_index(op.f("ix_run_qa_messages_agent_run_id"), table_name="run_qa_messages")
    op.drop_table("run_qa_messages")
