"""add ai agent run link to redo qa messages

Revision ID: 0079_add_ai_agent_run_link_to_redo_qa_messages
Revises: 0078_add_redo_qa_messages
Create Date: 2026-08-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0079_add_ai_agent_run_link_to_redo_qa_messages"
down_revision = "0078_add_redo_qa_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "redo_qa_messages",
        sa.Column("ai_agent_run_id", sa.Integer(), sa.ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index(op.f("ix_redo_qa_messages_ai_agent_run_id"), "redo_qa_messages", ["ai_agent_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_redo_qa_messages_ai_agent_run_id"), table_name="redo_qa_messages")
    op.drop_column("redo_qa_messages", "ai_agent_run_id")
