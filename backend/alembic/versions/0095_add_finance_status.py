"""add finances.status for per-line Beds24 invoice-item status

Revision ID: 0095_add_finance_status
Revises: 0094_add_ai_auto_draft_pending_beds24_update
Create Date: 2026-09-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0095_add_finance_status"
down_revision = "0094_add_ai_auto_draft_pending_beds24_update"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-line Beds24 invoice-item status (e.g. paid/unpaid), surfaced in the charges list.
    # Nullable: rows imported before this column existed carry no status, and it stays null
    # until the next Beds24 import/sync repopulates the finance rows.
    op.add_column("finances", sa.Column("status", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("finances", "status")
