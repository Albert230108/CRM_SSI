"""add action item tags join table

Revision ID: 0065_add_action_item_tags_join_table
Revises: 0064_add_beds24_availability_rooms_json
Create Date: 2026-08-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0065_add_action_item_tags_join_table"
down_revision = "0064_add_beds24_availability_rooms_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_item_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_item_id", sa.Integer(), sa.ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("action_tag_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("action_item_id", "tag_id", name="uq_action_item_tag"),
    )
    op.create_index(op.f("ix_action_item_tags_action_item_id"), "action_item_tags", ["action_item_id"], unique=False)
    op.create_index(op.f("ix_action_item_tags_tag_id"), "action_item_tags", ["tag_id"], unique=False)
    op.execute(
        "INSERT INTO action_item_tags (action_item_id, tag_id, position) "
        "SELECT id, tag_id, 0 FROM action_items WHERE tag_id IS NOT NULL"
    )
    op.drop_column("action_items", "tag_id")


def downgrade() -> None:
    op.add_column("action_items", sa.Column("tag_id", sa.Integer(), sa.ForeignKey("action_tag_definitions.id", ondelete="SET NULL"), nullable=True))
    op.execute(
        "UPDATE action_items SET tag_id = ("
        "SELECT tag_id FROM action_item_tags "
        "WHERE action_item_tags.action_item_id = action_items.id "
        "ORDER BY position, id LIMIT 1)"
    )
    op.drop_index(op.f("ix_action_item_tags_tag_id"), table_name="action_item_tags")
    op.drop_index(op.f("ix_action_item_tags_action_item_id"), table_name="action_item_tags")
    op.drop_table("action_item_tags")
