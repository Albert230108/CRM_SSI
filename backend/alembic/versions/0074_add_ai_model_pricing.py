"""add ai_model_pricing table

Revision ID: 0074_add_ai_model_pricing
Revises: 0073_add_attachment_ids_to_communication_reply_drafts
Create Date: 2026-08-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0074_add_ai_model_pricing"
down_revision = "0073_add_attachment_ids_to_communication_reply_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_model_pricing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(length=120), nullable=False, unique=True),
        sa.Column("input_cost_per_million_tokens", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("output_cost_per_million_tokens", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ai_model_pricing_model", "ai_model_pricing", ["model"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ai_model_pricing_model", table_name="ai_model_pricing")
    op.drop_table("ai_model_pricing")
