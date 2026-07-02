"""add full beds24 fields to tenants

Revision ID: 0005_add_full_beds24_fields_to_tenants
Revises: 0004_add_room_id_to_tenants
Create Date: 2026-07-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_add_full_beds24_fields_to_tenants"
down_revision = "0004_add_room_id_to_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("city", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("country", sa.String(length=100), nullable=True))
    op.add_column("tenants", sa.Column("zip_code", sa.String(length=50), nullable=True))
    op.add_column("tenants", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("company", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("language", sa.String(length=50), nullable=True))
    op.add_column("tenants", sa.Column("num_adults", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("num_children", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("num_nights", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("arrival_time", sa.String(length=50), nullable=True))
    op.add_column("tenants", sa.Column("departure_time", sa.String(length=50), nullable=True))
    op.add_column("tenants", sa.Column("room_name", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("source", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("referer", sa.String(length=500), nullable=True))
    op.add_column("tenants", sa.Column("total_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("tenants", sa.Column("commission", sa.Numeric(12, 2), nullable=True))
    op.add_column("tenants", sa.Column("deposit", sa.Numeric(12, 2), nullable=True))
    op.add_column("tenants", sa.Column("currency", sa.String(length=10), nullable=True))
    op.add_column("tenants", sa.Column("beds24_raw", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "beds24_raw")
    op.drop_column("tenants", "currency")
    op.drop_column("tenants", "deposit")
    op.drop_column("tenants", "commission")
    op.drop_column("tenants", "total_price")
    op.drop_column("tenants", "referer")
    op.drop_column("tenants", "source")
    op.drop_column("tenants", "room_name")
    op.drop_column("tenants", "departure_time")
    op.drop_column("tenants", "arrival_time")
    op.drop_column("tenants", "num_nights")
    op.drop_column("tenants", "num_children")
    op.drop_column("tenants", "num_adults")
    op.drop_column("tenants", "language")
    op.drop_column("tenants", "company")
    op.drop_column("tenants", "address")
    op.drop_column("tenants", "zip_code")
    op.drop_column("tenants", "country")
    op.drop_column("tenants", "city")
