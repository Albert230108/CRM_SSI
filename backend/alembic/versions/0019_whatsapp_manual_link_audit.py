"""whatsapp manual chat link audit fields and active-only chat uniqueness

Revision ID: 0019_whatsapp_manual_link_audit
Revises: 0018_tenant_channel_endpoints_chat_unique
Create Date: 2026-07-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_whatsapp_manual_link_audit"
down_revision = "0018_tenant_channel_endpoints_chat_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_channel_endpoints", sa.Column("chat_display_name", sa.String(length=255), nullable=True))
    op.add_column("tenant_channel_endpoints", sa.Column("source", sa.String(length=50), nullable=False, server_default="manual"))
    op.add_column("tenant_channel_endpoints", sa.Column("linked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("tenant_channel_endpoints", sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenant_channel_endpoints", sa.Column("unlinked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))

    # Existing endpoints predate the "manual link" flow; treat them as pre-existing registry
    # entries rather than manual links so the default doesn't misattribute history.
    op.execute("UPDATE tenant_channel_endpoints SET source = 'tenant_channel_endpoint_registry'")

    op.drop_constraint("uq_tenant_channel_endpoints_route", "tenant_channel_endpoints", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_channel_endpoints_route_active "
        "ON tenant_channel_endpoints (channel_type, provider, external_account_id, external_chat_namespace) "
        "WHERE is_active = true AND unlinked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_tenant_channel_endpoints_route_active")
    op.create_unique_constraint(
        "uq_tenant_channel_endpoints_route",
        "tenant_channel_endpoints",
        ["channel_type", "provider", "external_account_id", "external_chat_namespace"],
    )
    op.drop_column("tenant_channel_endpoints", "unlinked_by_user_id")
    op.drop_column("tenant_channel_endpoints", "unlinked_at")
    op.drop_column("tenant_channel_endpoints", "linked_by_user_id")
    op.drop_column("tenant_channel_endpoints", "source")
    op.drop_column("tenant_channel_endpoints", "chat_display_name")
