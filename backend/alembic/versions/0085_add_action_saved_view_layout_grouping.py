"""add layout, group_by and multi due_buckets to action saved views

Revision ID: 0085_add_action_saved_view_layout_grouping
Revises: 0084_add_action_planner_triggers_and_saved_views
Create Date: 2026-08-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0085_add_action_saved_view_layout_grouping"
down_revision = "0084_add_action_planner_triggers_and_saved_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_saved_views", sa.Column("due_buckets", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("action_saved_views", sa.Column("group_by", sa.String(length=12), nullable=False, server_default="none"))
    op.add_column("action_saved_views", sa.Column("layout", sa.String(length=8), nullable=False, server_default="list"))


def downgrade() -> None:
    op.drop_column("action_saved_views", "layout")
    op.drop_column("action_saved_views", "group_by")
    op.drop_column("action_saved_views", "due_buckets")
