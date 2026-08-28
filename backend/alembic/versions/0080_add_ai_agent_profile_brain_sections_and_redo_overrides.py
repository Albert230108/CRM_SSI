"""add ai agent profile brain sections and redo overrides

Revision ID: 0080_add_ai_agent_profile_brain_sections_and_redo_overrides
Revises: 0079_add_ai_agent_run_link_to_redo_qa_messages
Create Date: 2026-08-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0080_add_ai_agent_profile_brain_sections_and_redo_overrides"
down_revision = "0079_add_ai_agent_run_link_to_redo_qa_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_agent_profiles", sa.Column("redo_model", sa.String(length=120), nullable=True))
    op.add_column("ai_agent_profiles", sa.Column("redo_temperature", sa.Float(), nullable=True))
    op.add_column("ai_agent_profiles", sa.Column("redo_max_output_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "ai_agent_profiles",
        sa.Column("always_include_brain_sections", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("ai_agent_profiles", "always_include_brain_sections")
    op.drop_column("ai_agent_profiles", "redo_max_output_tokens")
    op.drop_column("ai_agent_profiles", "redo_temperature")
    op.drop_column("ai_agent_profiles", "redo_model")
