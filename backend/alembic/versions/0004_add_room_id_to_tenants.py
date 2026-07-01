"""add room_id to tenants

Revision ID: 0004_add_room_id_to_tenants
Revises: 0003_add_type_to_finances
Create Date: 2026-07-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_add_room_id_to_tenants"
down_revision = "0003_add_type_to_finances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("room_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "room_id")
