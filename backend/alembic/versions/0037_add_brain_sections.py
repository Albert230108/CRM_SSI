"""add brain sections and template description

Revision ID: 0037_add_brain_sections
Revises: 0036_add_communication_attachments
Create Date: 2026-08-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0037_add_brain_sections"
down_revision = "0036_add_communication_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brain_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("path", sa.String(length=600), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["brain_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("parent_id", "slug", name="uq_brain_sections_parent_slug"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_brain_sections_parent_id"), "brain_sections", ["parent_id"])
    op.create_index(op.f("ix_brain_sections_path"), "brain_sections", ["path"], unique=True)

    op.create_table(
        "ai_reply_template_brain_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("brain_section_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["ai_reply_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["brain_section_id"], ["brain_sections.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("template_id", "brain_section_id", name="uq_ai_template_brain_section"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_reply_template_brain_sections_template_id"),
        "ai_reply_template_brain_sections",
        ["template_id"],
    )
    op.create_index(
        op.f("ix_ai_reply_template_brain_sections_brain_section_id"),
        "ai_reply_template_brain_sections",
        ["brain_section_id"],
    )

    op.add_column("ai_reply_templates", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_reply_templates", "description")
    op.drop_index(
        op.f("ix_ai_reply_template_brain_sections_brain_section_id"),
        table_name="ai_reply_template_brain_sections",
    )
    op.drop_index(
        op.f("ix_ai_reply_template_brain_sections_template_id"),
        table_name="ai_reply_template_brain_sections",
    )
    op.drop_table("ai_reply_template_brain_sections")
    op.drop_index(op.f("ix_brain_sections_path"), table_name="brain_sections")
    op.drop_index(op.f("ix_brain_sections_parent_id"), table_name="brain_sections")
    op.drop_table("brain_sections")
