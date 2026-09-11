"""add ai_auto_drafts.pending_beds24_update

The sales-manager agent's new "update" task stages a Beds24 invoice-item update on the draft
instead of pushing it immediately. It is only sent (send_scheduled_draft) once a human approves
the draft, never by the auto-send timer.

Revision ID: 0094_add_ai_auto_draft_pending_beds24_update
Revises: 0093_backfill_ai_agent_profile_instruction_sections
Create Date: 2026-09-11 00:00:02.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0094_add_ai_auto_draft_pending_beds24_update"
down_revision = "0093_backfill_ai_agent_profile_instruction_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_auto_drafts",
        sa.Column("pending_beds24_update", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_auto_drafts", "pending_beds24_update")
