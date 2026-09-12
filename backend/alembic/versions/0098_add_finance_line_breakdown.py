"""add finances qty/unit_price/vat_rate for the per-line charges breakdown

Revision ID: 0098_add_finance_line_breakdown
Revises: 0097_add_tenant_sub_status
Create Date: 2026-09-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0098_add_finance_line_breakdown"
down_revision = "0097_add_tenant_sub_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("finances", sa.Column("qty", sa.Numeric(12, 2), nullable=True))
    op.add_column("finances", sa.Column("unit_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("finances", sa.Column("vat_rate", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("finances", "vat_rate")
    op.drop_column("finances", "unit_price")
    op.drop_column("finances", "qty")
