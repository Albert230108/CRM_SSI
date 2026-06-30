"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-06-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("booking_id", sa.String(length=100), nullable=False),
        sa.Column("responsible_comm", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_tenants_id"), "tenants", ["id"], unique=False)
    op.create_index(op.f("ix_tenants_name"), "tenants", ["name"], unique=False)
    op.create_index(op.f("ix_tenants_booking_id"), "tenants", ["booking_id"], unique=True)

    op.create_table(
        "finances",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_finances_id"), "finances", ["id"], unique=False)
    op.create_index(op.f("ix_finances_tenant_id"), "finances", ["tenant_id"], unique=False)

    op.create_table(
        "communications",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_communications_id"), "communications", ["id"], unique=False)
    op.create_index(op.f("ix_communications_tenant_id"), "communications", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_communications_tenant_id"), table_name="communications")
    op.drop_index(op.f("ix_communications_id"), table_name="communications")
    op.drop_table("communications")

    op.drop_index(op.f("ix_finances_tenant_id"), table_name="finances")
    op.drop_index(op.f("ix_finances_id"), table_name="finances")
    op.drop_table("finances")

    op.drop_index(op.f("ix_tenants_booking_id"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_name"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_id"), table_name="tenants")
    op.drop_table("tenants")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
