"""add formatter role and tenant settings

Revision ID: 0070_add_formatter_role_and_settings
Revises: 0069_default_action_writer_payments
Create Date: 2026-08-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0070_add_formatter_role_and_settings"
down_revision = "0069_default_action_writer_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_ai_settings",
        sa.Column("formatter_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "tenant_ai_settings",
        sa.Column("formatter_profile_id", sa.Integer(), sa.ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_ai_settings", "formatter_profile_id")
    op.drop_column("tenant_ai_settings", "formatter_enabled")
