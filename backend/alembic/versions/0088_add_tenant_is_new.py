"""add tenants.is_new for the "New import" sidebar badge

Revision ID: 0088_add_tenant_is_new
Revises: 0087_add_device_tokens_and_push
Create Date: 2026-09-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0088_add_tenant_is_new"
down_revision = "0087_add_device_tokens_and_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New tenants (import, manual create, Beds24 sync/webhook) default to is_new=true via the
    # server default, so no creation site needs to set it explicitly.
    op.add_column(
        "tenants",
        sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    # Existing tenants are not "new" - clear the badge for everything already imported.
    op.execute("UPDATE tenants SET is_new = false")


def downgrade() -> None:
    op.drop_column("tenants", "is_new")
