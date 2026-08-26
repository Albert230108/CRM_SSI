"""make action_items.tenant_id nullable

Revision ID: 0075_action_items_tenant_id_nullable
Revises: 0074_add_ai_model_pricing
Create Date: 2026-08-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0075_action_items_tenant_id_nullable"
down_revision = "0074_add_ai_model_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("action_items", "tenant_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("action_items", "tenant_id", existing_type=sa.Integer(), nullable=False)
