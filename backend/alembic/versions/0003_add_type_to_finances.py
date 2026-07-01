"""add type to finances

Revision ID: 0003_add_type_to_finances
Revises: 0002_add_mobile_check_in_check_out_notes_to_tenants
Create Date: 2026-07-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_add_type_to_finances"
down_revision = "0002_add_mobile_check_in_check_out_notes_to_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "finances",
        sa.Column("type", sa.String(length=10), nullable=False, server_default="charge"),
    )


def downgrade() -> None:
    op.drop_column("finances", "type")
