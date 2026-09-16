"""fix decouple beds24 backfill: clear execution_status on empty-payload rows

Revision ID: 0103_fix_ai_auto_draft_execution_status_backfill
Revises: 0102_add_ai_auto_draft_execution_status
Create Date: 2026-09-16 00:00:00.000000
"""
from alembic import op


revision = "0103_fix_ai_auto_draft_execution_status_backfill"
down_revision = "0102_add_ai_auto_draft_execution_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0102 backfilled `execution_status='pending'` WHERE `pending_execution IS NOT NULL`, but
    # `pending_execution` is a JSON column and a stored JSON `null`/`{}` is not SQL NULL - so
    # empty-payload rows were wrongly marked "pending". Those surface as un-actionable Beds24
    # cards whose approve/reject endpoints 409 for having no payload. Correct only those rows,
    # reusing 0102's own two-branch intent (executed if the executor already ran, else no action).
    op.execute(
        "UPDATE ai_auto_drafts "
        "SET execution_status = CASE WHEN executor_run_id IS NOT NULL THEN 'executed' ELSE NULL END "
        "WHERE execution_status = 'pending' "
        "AND (pending_execution IS NULL "
        "OR pending_execution::jsonb = 'null'::jsonb "
        "OR pending_execution::jsonb = '{}'::jsonb)"
    )


def downgrade() -> None:
    # Data-only correction: the pre-fix "pending" values were themselves wrong (they pointed at
    # rows with no actionable payload), so there is nothing meaningful to restore.
    pass
