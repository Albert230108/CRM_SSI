"""allow redo request logs to reference a manual planner run instead of an ai_auto_draft

Revision ID: 0059_add_redo_log_agent_run_link
Revises: 0058_add_memory_qa_messages
Create Date: 2026-08-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0059_add_redo_log_agent_run_link"
down_revision = "0058_add_memory_qa_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The manual "Run planner" redo (reply box, no AiAutoDraft row) needs a redo log entry too,
    # so ai_auto_draft_id can no longer be required - it links to whichever of the two exists.
    op.alter_column("redo_request_logs", "ai_auto_draft_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "redo_request_logs",
        sa.Column("ai_agent_run_id", sa.Integer(), sa.ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index(op.f("ix_redo_request_logs_ai_agent_run_id"), "redo_request_logs", ["ai_agent_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_redo_request_logs_ai_agent_run_id"), table_name="redo_request_logs")
    op.drop_column("redo_request_logs", "ai_agent_run_id")
    op.alter_column("redo_request_logs", "ai_auto_draft_id", existing_type=sa.Integer(), nullable=False)
