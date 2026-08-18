"""add color to brain_sections

Revision ID: 0042_add_brain_section_color
Revises: 0041_add_agent_prompt_blocks
Create Date: 2026-08-18 00:00:04.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0042_add_brain_section_color"
down_revision = "0041_add_agent_prompt_blocks"
branch_labels = None
depends_on = None


def _has_column(connection, table_name: str, column_name: str) -> bool:
    return bool(
        connection.execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND column_name = :column_name
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).first()
    )


def upgrade() -> None:
    connection = op.get_bind()
    if not _has_column(connection, "brain_sections", "color"):
        op.add_column(
            "brain_sections",
            sa.Column("color", sa.String(length=7), nullable=True),
        )


def downgrade() -> None:
    connection = op.get_bind()
    if _has_column(connection, "brain_sections", "color"):
        op.drop_column("brain_sections", "color")
