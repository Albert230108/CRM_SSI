"""add redo request log processing fields

Revision ID: 0060_add_redo_request_log_processing
Revises: 0059_add_redo_log_agent_run_link
Create Date: 2026-08-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0060_add_redo_request_log_processing"
down_revision = "0059_add_redo_log_agent_run_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "redo_request_logs",
        sa.Column("memory_redo_run_id", sa.Integer(), sa.ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("redo_request_logs", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_redo_request_logs_memory_redo_run_id"), "redo_request_logs", ["memory_redo_run_id"], unique=False)
    op.create_index(op.f("ix_redo_request_logs_processed_at"), "redo_request_logs", ["processed_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_redo_request_logs_processed_at"), table_name="redo_request_logs")
    op.drop_index(op.f("ix_redo_request_logs_memory_redo_run_id"), table_name="redo_request_logs")
    op.drop_column("redo_request_logs", "processed_at")
    op.drop_column("redo_request_logs", "memory_redo_run_id")
