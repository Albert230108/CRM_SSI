"""backfill ai_agent_profiles.instruction_sections from instructions

Every profile with non-empty `instructions` gets a single unlabeled card holding the verbatim
text, so opening the new Agent Instructions grid shows exactly what was there before - nothing
truncated or reordered - and the derived text (build_instructions_text of one unlabeled card)
is byte-for-byte identical to the original, since a consumer's existing `.strip()` already
normalizes the same whitespace. A profile with empty/whitespace-only instructions gets an empty
board instead of a stray blank card. `instructions` itself is never touched.

Reversible: the down-migration only drops the two columns added in the previous migration -
0091's `instructions` column and its data are untouched either way, so downgrading loses nothing.

Revision ID: 0093_backfill_ai_agent_profile_instruction_sections
Revises: 0092_add_ai_agent_profile_instruction_grid
Create Date: 2026-09-11 00:00:01.000000
"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = "0093_backfill_ai_agent_profile_instruction_sections"
down_revision = "0092_add_ai_agent_profile_instruction_grid"
branch_labels = None
depends_on = None

# Matches frontend/src/lib/aiTemplateCanvas.ts's CARD_WIDTH/CARD_HEIGHT - a data migration
# can't import frontend code, so the single-card default size is duplicated here deliberately.
_CARD_WIDTH = 288
_CARD_HEIGHT = 192


def upgrade() -> None:
    connection = op.get_bind()
    profiles = sa.table(
        "ai_agent_profiles",
        sa.column("id", sa.Integer),
        sa.column("instructions", sa.Text),
        sa.column("instruction_sections", sa.JSON),
        sa.column("instruction_canvas_notes", sa.JSON),
    )

    rows = connection.execute(sa.select(profiles.c.id, profiles.c.instructions)).fetchall()
    for row in rows:
        text = (row.instructions or "").strip()
        sections = (
            [
                {
                    "id": str(uuid.uuid4()),
                    "label": "",
                    "content": text,
                    "order": 0,
                    "x": 0,
                    "y": 0,
                    "w": _CARD_WIDTH,
                    "h": _CARD_HEIGHT,
                    "z": 0,
                }
            ]
            if text
            else []
        )
        connection.execute(
            profiles.update()
            .where(profiles.c.id == row.id)
            .values(instruction_sections=sections, instruction_canvas_notes=[])
        )


def downgrade() -> None:
    # Nothing to reverse here: this migration only wrote data into columns that
    # 0092_add_ai_agent_profile_instruction_grid's own downgrade drops. Left as a no-op so
    # downgrading step-by-step never fails.
    pass
