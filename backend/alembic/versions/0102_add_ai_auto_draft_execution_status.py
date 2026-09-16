"""decouple beds24 approval: add ai_auto_drafts.execution_status

Revision ID: 0102_add_ai_auto_draft_execution_status
Revises: 0101_assistant_run_logging
Create Date: 2026-09-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0102_add_ai_auto_draft_execution_status"
down_revision = "0101_assistant_run_logging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tracks the prepared Beds24 write's own lifecycle, separate from the message `status`, so the
    # message approval and the Beds24 approval can be actioned independently in the AI Drafts UI.
    op.add_column("ai_auto_drafts", sa.Column("execution_status", sa.String(length=20), nullable=True))
    op.create_index(op.f("ix_ai_auto_drafts_execution_status"), "ai_auto_drafts", ["execution_status"])
    # Backfill existing rows: a draft still carrying a payload is "pending"; one whose executor run
    # already fired and cleared the payload is "executed"; everything else has no Beds24 action.
    op.execute("UPDATE ai_auto_drafts SET execution_status = 'pending' WHERE pending_execution IS NOT NULL")
    op.execute(
        "UPDATE ai_auto_drafts SET execution_status = 'executed' "
        "WHERE pending_execution IS NULL AND executor_run_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_auto_drafts_execution_status"), table_name="ai_auto_drafts")
    op.drop_column("ai_auto_drafts", "execution_status")
