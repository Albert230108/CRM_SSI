"""add tenant email addresses

Revision ID: 0028_add_tenant_email_addresses
Revises: 0027_add_ai_template_notes_and_auto_apply_setting
Create Date: 2026-07-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0028_add_tenant_email_addresses"
down_revision = "0027_add_ai_template_notes_and_auto_apply_setting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_email_addresses",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("beds24_info_item_id", sa.String(length=100), nullable=True),
        sa.Column("beds24_sync_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("linked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlinked_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_tenant_email_addresses_tenant_id"), "tenant_email_addresses", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_email_addresses_email"), "tenant_email_addresses", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tenant_email_addresses_email"), table_name="tenant_email_addresses")
    op.drop_index(op.f("ix_tenant_email_addresses_tenant_id"), table_name="tenant_email_addresses")
    op.drop_table("tenant_email_addresses")
