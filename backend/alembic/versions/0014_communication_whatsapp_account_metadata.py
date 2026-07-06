"""add whatsapp account metadata to communications

Revision ID: 0014_communication_whatsapp_account_metadata
Revises: 0013_add_communication_provider_message_id
Create Date: 2026-07-06 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_communication_whatsapp_account_metadata"
down_revision = "0013_add_communication_provider_message_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("communications", sa.Column("provider", sa.String(length=100), nullable=True))
    op.add_column("communications", sa.Column("external_account_id", sa.String(length=255), nullable=True))
    op.add_column("communications", sa.Column("external_phone_id", sa.String(length=255), nullable=True))
    op.add_column("communications", sa.Column("external_chat_namespace", sa.String(length=255), nullable=True))
    op.add_column("communications", sa.Column("whatsapp_chat_id", sa.String(length=255), nullable=True))
    op.drop_index(op.f("ix_communications_provider_message_id"), table_name="communications")
    op.create_unique_constraint("uq_communications_tenant_provider_message_id", "communications", ["tenant_id", "provider_message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_communications_tenant_provider_message_id", "communications", type_="unique")
    op.create_index(op.f("ix_communications_provider_message_id"), "communications", ["provider_message_id"], unique=True)
    op.drop_column("communications", "whatsapp_chat_id")
    op.drop_column("communications", "external_chat_namespace")
    op.drop_column("communications", "external_phone_id")
    op.drop_column("communications", "external_account_id")
    op.drop_column("communications", "provider")
