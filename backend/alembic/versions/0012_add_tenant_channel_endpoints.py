"""add tenant channel endpoints

Revision ID: 0012_add_tenant_channel_endpoints
Revises: 0011_add_communication_direction
Create Date: 2026-07-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_add_tenant_channel_endpoints"
down_revision = "0011_add_communication_direction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_channel_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("external_phone_id", sa.String(length=255), nullable=True),
        sa.Column("external_chat_namespace", sa.String(length=255), nullable=True),
        sa.Column("webhook_token", sa.String(length=255), nullable=True),
        sa.Column("signing_secret", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("channel_type", "provider", "external_account_id", name="uq_tenant_channel_endpoints_route"),
    )
    op.create_index(op.f("ix_tenant_channel_endpoints_id"), "tenant_channel_endpoints", ["id"], unique=False)
    op.create_index(op.f("ix_tenant_channel_endpoints_tenant_id"), "tenant_channel_endpoints", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_channel_endpoints_channel_type"), "tenant_channel_endpoints", ["channel_type"], unique=False)
    op.create_index(op.f("ix_tenant_channel_endpoints_provider"), "tenant_channel_endpoints", ["provider"], unique=False)
    op.create_index(op.f("ix_tenant_channel_endpoints_external_account_id"), "tenant_channel_endpoints", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_tenant_channel_endpoints_external_phone_id"), "tenant_channel_endpoints", ["external_phone_id"], unique=False)
    op.create_index(op.f("ix_tenant_channel_endpoints_external_chat_namespace"), "tenant_channel_endpoints", ["external_chat_namespace"], unique=False)
    op.create_index(op.f("ix_tenant_channel_endpoints_webhook_token"), "tenant_channel_endpoints", ["webhook_token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_tenant_channel_endpoints_webhook_token"), table_name="tenant_channel_endpoints")
    op.drop_index(op.f("ix_tenant_channel_endpoints_external_chat_namespace"), table_name="tenant_channel_endpoints")
    op.drop_index(op.f("ix_tenant_channel_endpoints_external_phone_id"), table_name="tenant_channel_endpoints")
    op.drop_index(op.f("ix_tenant_channel_endpoints_external_account_id"), table_name="tenant_channel_endpoints")
    op.drop_index(op.f("ix_tenant_channel_endpoints_provider"), table_name="tenant_channel_endpoints")
    op.drop_index(op.f("ix_tenant_channel_endpoints_channel_type"), table_name="tenant_channel_endpoints")
    op.drop_index(op.f("ix_tenant_channel_endpoints_tenant_id"), table_name="tenant_channel_endpoints")
    op.drop_index(op.f("ix_tenant_channel_endpoints_id"), table_name="tenant_channel_endpoints")
    op.drop_table("tenant_channel_endpoints")
