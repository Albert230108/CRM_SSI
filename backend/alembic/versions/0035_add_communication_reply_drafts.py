"""add communication reply drafts

Revision ID: 0035_add_communication_reply_drafts
Revises: 0034_add_tenant_draft_notes
Create Date: 2026-07-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0035_add_communication_reply_drafts"
down_revision = "0034_add_tenant_draft_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_reply_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("email_thread_id", sa.Integer(), nullable=True),
        sa.Column("whatsapp_endpoint_id", sa.Integer(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["email_thread_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["whatsapp_endpoint_id"], ["tenant_channel_endpoints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.CheckConstraint(
            "(channel = 'email' AND email_thread_id IS NOT NULL AND whatsapp_endpoint_id IS NULL)"
            " OR (channel = 'whatsapp' AND whatsapp_endpoint_id IS NOT NULL AND email_thread_id IS NULL)",
            name="ck_communication_reply_drafts_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_communication_reply_drafts_tenant_id"), "communication_reply_drafts", ["tenant_id"])
    op.create_index(
        op.f("ix_communication_reply_drafts_email_thread_id"), "communication_reply_drafts", ["email_thread_id"]
    )
    op.create_index(
        op.f("ix_communication_reply_drafts_whatsapp_endpoint_id"),
        "communication_reply_drafts",
        ["whatsapp_endpoint_id"],
    )
    # Partial indexes: only one scope column is populated per row, so a plain composite
    # unique index would be defeated by the NULL in the other column.
    op.create_index(
        "uq_communication_reply_drafts_email",
        "communication_reply_drafts",
        ["tenant_id", "email_thread_id"],
        unique=True,
        postgresql_where=sa.text("channel = 'email'"),
        sqlite_where=sa.text("channel = 'email'"),
    )
    op.create_index(
        "uq_communication_reply_drafts_whatsapp",
        "communication_reply_drafts",
        ["tenant_id", "whatsapp_endpoint_id"],
        unique=True,
        postgresql_where=sa.text("channel = 'whatsapp'"),
        sqlite_where=sa.text("channel = 'whatsapp'"),
    )


def downgrade() -> None:
    op.drop_index("uq_communication_reply_drafts_whatsapp", table_name="communication_reply_drafts")
    op.drop_index("uq_communication_reply_drafts_email", table_name="communication_reply_drafts")
    op.drop_index(
        op.f("ix_communication_reply_drafts_whatsapp_endpoint_id"), table_name="communication_reply_drafts"
    )
    op.drop_index(op.f("ix_communication_reply_drafts_email_thread_id"), table_name="communication_reply_drafts")
    op.drop_index(op.f("ix_communication_reply_drafts_tenant_id"), table_name="communication_reply_drafts")
    op.drop_table("communication_reply_drafts")
