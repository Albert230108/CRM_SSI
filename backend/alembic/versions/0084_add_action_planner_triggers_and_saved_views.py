"""add action planner triggers, ai instruction, due time, and saved views

Revision ID: 0084_add_action_planner_triggers_and_saved_views
Revises: 0083_add_bulk_planner_schedule_extra_instructions
Create Date: 2026-08-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0084_add_action_planner_triggers_and_saved_views"
down_revision = "0083_add_bulk_planner_schedule_extra_instructions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_items", sa.Column("ai_instruction", sa.Text(), nullable=True))
    op.add_column("action_items", sa.Column("due_time", sa.Time(), nullable=True))
    op.add_column("action_items", sa.Column("planner_triggered_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "action_tag_definitions",
        sa.Column("triggers_planner", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "action_saved_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("priority", sa.String(length=4), nullable=True),
        sa.Column("tag_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("tag_match", sa.String(length=4), nullable=False, server_default="any"),
        sa.Column("due_bucket", sa.String(length=20), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="all"),
        sa.Column("sort_field", sa.String(length=20), nullable=False, server_default="due_date"),
        sa.Column("sort_dir", sa.String(length=4), nullable=False, server_default="asc"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("action_saved_views")
    op.drop_column("action_tag_definitions", "triggers_planner")
    op.drop_column("action_items", "planner_triggered_at")
    op.drop_column("action_items", "due_time")
    op.drop_column("action_items", "ai_instruction")
