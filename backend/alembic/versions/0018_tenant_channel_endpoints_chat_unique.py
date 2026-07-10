"""tenant channel endpoints route uses chat identity

Revision ID: 0018_tenant_channel_endpoints_chat_unique
Revises: 0017_tenant_phone_aliases
Create Date: 2026-07-10 00:00:00.000000
"""

from alembic import op


revision = "0018_tenant_channel_endpoints_chat_unique"
down_revision = "0017_tenant_phone_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_tenant_channel_endpoints_route", "tenant_channel_endpoints", type_="unique")
    op.create_unique_constraint(
        "uq_tenant_channel_endpoints_route",
        "tenant_channel_endpoints",
        ["channel_type", "provider", "external_account_id", "external_chat_namespace"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_tenant_channel_endpoints_route", "tenant_channel_endpoints", type_="unique")
    op.create_unique_constraint(
        "uq_tenant_channel_endpoints_route",
        "tenant_channel_endpoints",
        ["channel_type", "provider", "external_account_id"],
    )

