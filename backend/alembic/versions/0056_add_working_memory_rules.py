"""add working memory rules

Revision ID: 0056_add_working_memory_rules
Revises: 0055_add_beds24_availability
Create Date: 2026-08-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0056_add_working_memory_rules"
down_revision = "0055_add_beds24_availability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "working_memory_rules",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("condition_text", sa.Text(), nullable=False),
        sa.Column("action_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("working_memory_rules")
