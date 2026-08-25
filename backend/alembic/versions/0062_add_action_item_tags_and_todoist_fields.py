"""add action item tags and todoist-style fields

Revision ID: 0062_add_action_item_tags_and_todoist_fields
Revises: 0061_add_action_writer_role
Create Date: 2026-08-25 00:00:00.000001
"""
from alembic import op
import sqlalchemy as sa


revision = "0062_add_action_item_tags_and_todoist_fields"
down_revision = "0061_add_action_writer_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_tag_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_action_tag_definitions_name"), "action_tag_definitions", ["name"], unique=True)

    op.add_column(
        "action_items",
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("action_tag_definitions.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("action_items", sa.Column("priority", sa.String(length=4), nullable=True))
    op.add_column("action_items", sa.Column("recurrence_interval_days", sa.Integer(), nullable=True))
    op.add_column("action_items", sa.Column("recurrence_anchor", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("action_items", "recurrence_anchor")
    op.drop_column("action_items", "recurrence_interval_days")
    op.drop_column("action_items", "priority")
    op.drop_column("action_items", "tag_id")

    op.drop_index(op.f("ix_action_tag_definitions_name"), table_name="action_tag_definitions")
    op.drop_table("action_tag_definitions")
