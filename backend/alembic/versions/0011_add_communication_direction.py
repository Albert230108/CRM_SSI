"""add communication direction

Revision ID: 0011_add_communication_direction
Revises: 0010_gmail_conversations
Create Date: 2026-07-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_add_communication_direction"
down_revision = "0010_gmail_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "communications",
        sa.Column("direction", sa.String(length=20), nullable=False, server_default=sa.text("'outbound'")),
    )


def downgrade() -> None:
    op.drop_column("communications", "direction")
