"""add tenant draft notes

Revision ID: 0034_add_tenant_draft_notes
Revises: 0033_add_tenant_notes_history
Create Date: 2026-07-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0034_add_tenant_draft_notes"
down_revision = "0033_add_tenant_notes_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("draft_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "draft_notes")
