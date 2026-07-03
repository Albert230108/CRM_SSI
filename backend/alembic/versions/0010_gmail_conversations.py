"""add gmail conversations and accounts

Revision ID: 0010_gmail_conversations
Revises: 0009_extend_beds24_webhook_logs
Create Date: 2026-07-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_gmail_conversations"
down_revision = "0009_extend_beds24_webhook_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email_address", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("google_account_id", sa.String(length=255), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_uri", sa.String(length=500), nullable=True),
        sa.Column("scopes_json", sa.JSON(), nullable=True),
        sa.Column("credentials_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_history_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_gmail_accounts_id"), "gmail_accounts", ["id"], unique=False)
    op.create_index(op.f("ix_gmail_accounts_email_address"), "gmail_accounts", ["email_address"], unique=True)
    op.create_index(op.f("ix_gmail_accounts_google_account_id"), "gmail_accounts", ["google_account_id"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_account_id", sa.Integer(), nullable=True),
        sa.Column("provider_thread_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preview_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_conversations_id"), "conversations", ["id"], unique=False)
    op.create_index(op.f("ix_conversations_provider"), "conversations", ["provider"], unique=False)
    op.create_index(op.f("ix_conversations_provider_account_id"), "conversations", ["provider_account_id"], unique=False)
    op.create_index(op.f("ix_conversations_provider_thread_id"), "conversations", ["provider_thread_id"], unique=False)
    op.create_index(op.f("ix_conversations_tenant_id"), "conversations", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_conversations_last_message_at"), "conversations", ["last_message_at"], unique=False)

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("sender_email", sa.String(length=255), nullable=True),
        sa.Column("recipient_email", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_conversation_messages_id"), "conversation_messages", ["id"], unique=False)
    op.create_index(op.f("ix_conversation_messages_conversation_id"), "conversation_messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_conversation_messages_provider"), "conversation_messages", ["provider"], unique=False)
    op.create_index(op.f("ix_conversation_messages_provider_message_id"), "conversation_messages", ["provider_message_id"], unique=True)
    op.create_index(op.f("ix_conversation_messages_sender_email"), "conversation_messages", ["sender_email"], unique=False)
    op.create_index(op.f("ix_conversation_messages_sent_at"), "conversation_messages", ["sent_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_messages_sent_at"), table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_sender_email"), table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_provider_message_id"), table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_provider"), table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_conversation_id"), table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_id"), table_name="conversation_messages")
    op.drop_table("conversation_messages")

    op.drop_index(op.f("ix_conversations_last_message_at"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_tenant_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_provider_thread_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_provider_account_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_provider"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_id"), table_name="conversations")
    op.drop_table("conversations")

    op.drop_index(op.f("ix_gmail_accounts_google_account_id"), table_name="gmail_accounts", if_exists=True)
    op.drop_index(op.f("ix_gmail_accounts_email_address"), table_name="gmail_accounts")
    op.drop_index(op.f("ix_gmail_accounts_id"), table_name="gmail_accounts")
    op.drop_table("gmail_accounts")
