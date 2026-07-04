"""add communication provider message id

Revision ID: 0013_add_communication_provider_message_id
Revises: 0012_add_tenant_channel_endpoints
Create Date: 2026-07-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_add_communication_provider_message_id"
down_revision = "0012_add_tenant_channel_endpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("communications", sa.Column("provider_message_id", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_communications_provider_message_id"), "communications", ["provider_message_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_communications_provider_message_id"), table_name="communications")
    op.drop_column("communications", "provider_message_id")
