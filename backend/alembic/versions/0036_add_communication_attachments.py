"""add communication attachments

Revision ID: 0036_add_communication_attachments
Revises: 0035_add_communication_reply_drafts
Create Date: 2026-07-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0036_add_communication_attachments"
down_revision = "0035_add_communication_reply_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("tenant_id", "sha256", name="uq_communication_attachments_tenant_sha256"),
        sa.UniqueConstraint("storage_key", name="uq_communication_attachments_storage_key"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_communication_attachments_tenant_id"), "communication_attachments", ["tenant_id"]
    )

    op.create_table(
        "communication_attachment_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("attachment_id", sa.Integer(), nullable=False),
        sa.Column("communication_id", sa.Integer(), nullable=True),
        sa.Column("conversation_message_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["communication_attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["communication_id"], ["communications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_message_id"], ["conversation_messages.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "communication_id IS NOT NULL OR conversation_message_id IS NOT NULL",
            name="ck_communication_attachment_links_target",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_communication_attachment_links_attachment_id"),
        "communication_attachment_links",
        ["attachment_id"],
    )
    op.create_index(
        op.f("ix_communication_attachment_links_communication_id"),
        "communication_attachment_links",
        ["communication_id"],
    )
    op.create_index(
        op.f("ix_communication_attachment_links_conversation_message_id"),
        "communication_attachment_links",
        ["conversation_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_communication_attachment_links_conversation_message_id"),
        table_name="communication_attachment_links",
    )
    op.drop_index(
        op.f("ix_communication_attachment_links_communication_id"), table_name="communication_attachment_links"
    )
    op.drop_index(
        op.f("ix_communication_attachment_links_attachment_id"), table_name="communication_attachment_links"
    )
    op.drop_table("communication_attachment_links")

    op.drop_index(op.f("ix_communication_attachments_tenant_id"), table_name="communication_attachments")
    op.drop_table("communication_attachments")
