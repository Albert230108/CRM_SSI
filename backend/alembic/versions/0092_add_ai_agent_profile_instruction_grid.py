"""add instruction_sections/instruction_canvas_notes to ai_agent_profiles

Storage for the Agent Instructions grid (the same card-canvas UX as the AI Templates board).
`instructions` (Text) stays as the retained, always-in-sync derived value every existing
consumer reads - these two columns are only the authoring UI's card representation. See
0093_backfill_ai_agent_profile_instruction_sections for the data migration that populates them
from existing `instructions` text, kept separate so either half can be rolled back independently.

Revision ID: 0092_add_ai_agent_profile_instruction_grid
Revises: 0091_add_onedrive_delegated_auth
Create Date: 2026-09-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0092_add_ai_agent_profile_instruction_grid"
down_revision = "0091_add_onedrive_delegated_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_agent_profiles",
        sa.Column("instruction_sections", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "ai_agent_profiles",
        sa.Column("instruction_canvas_notes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("ai_agent_profiles", "instruction_canvas_notes")
    op.drop_column("ai_agent_profiles", "instruction_sections")
