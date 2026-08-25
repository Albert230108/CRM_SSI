"""add beds24 availability rooms json

Revision ID: 0064_add_beds24_availability_rooms_json
Revises: 0063_add_ai_auto_draft_resolution_reason
Create Date: 2026-08-25 00:00:00.000003
"""
from alembic import op
import sqlalchemy as sa


revision = "0064_add_beds24_availability_rooms_json"
down_revision = "0063_add_ai_auto_draft_resolution_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("beds24_availability_summary", sa.Column("rooms_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("beds24_availability_summary", "rooms_json")
