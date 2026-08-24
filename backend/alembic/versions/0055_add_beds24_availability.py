"""add beds24 availability summary cache and include_availability flags

Revision ID: 0055_add_beds24_availability
Revises: 0054_add_brain_fields_and_action_items
Create Date: 2026-08-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0055_add_beds24_availability"
down_revision = "0054_add_brain_fields_and_action_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beds24_availability_summary",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
    )

    op.add_column(
        "ai_agent_profiles",
        sa.Column("include_availability", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "ai_reply_templates",
        sa.Column("include_availability", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("ai_reply_templates", "include_availability")
    op.drop_column("ai_agent_profiles", "include_availability")
    op.drop_table("beds24_availability_summary")
