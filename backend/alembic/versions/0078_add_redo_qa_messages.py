"""add redo qa messages

Revision ID: 0078_add_redo_qa_messages
Revises: 0077_add_rich_fields_to_communication_reply_drafts
Create Date: 2026-08-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0078_add_redo_qa_messages"
down_revision = "0077_add_rich_fields_to_communication_reply_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "redo_qa_messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("redo_request_log_id", sa.Integer(), sa.ForeignKey("redo_request_logs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("asked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_redo_qa_messages_redo_request_log_id"), "redo_qa_messages", ["redo_request_log_id"], unique=False)
    op.create_index(op.f("ix_redo_qa_messages_created_at"), "redo_qa_messages", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_redo_qa_messages_created_at"), table_name="redo_qa_messages")
    op.drop_index(op.f("ix_redo_qa_messages_redo_request_log_id"), table_name="redo_qa_messages")
    op.drop_table("redo_qa_messages")
