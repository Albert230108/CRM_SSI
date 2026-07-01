"""add mobile check_in check_out notes to tenants

Revision ID: 0002_add_mobile_check_in_check_out_notes_to_tenants
Revises: 0001_initial
Create Date: 2026-07-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_add_mobile_check_in_check_out_notes_to_tenants"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("mobile", sa.String(length=100), nullable=True))
    op.add_column("tenants", sa.Column("check_in", sa.String(length=50), nullable=True))
    op.add_column("tenants", sa.Column("check_out", sa.String(length=50), nullable=True))
    op.add_column("tenants", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "notes")
    op.drop_column("tenants", "check_out")
    op.drop_column("tenants", "check_in")
    op.drop_column("tenants", "mobile")
