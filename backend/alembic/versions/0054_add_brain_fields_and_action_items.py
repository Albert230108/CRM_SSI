"""add brain field definitions, tenant brain field values, and action items

Revision ID: 0054_add_brain_fields_and_action_items
Revises: 0053_add_conversation_thread_uniqueness
Create Date: 2026-08-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0054_add_brain_fields_and_action_items"
down_revision = "0053_add_conversation_thread_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brain_field_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("ai_instruction", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("key", name="uq_brain_field_definitions_key"),
    )
    op.create_index(op.f("ix_brain_field_definitions_key"), "brain_field_definitions", ["key"], unique=True)

    op.create_table(
        "tenant_brain_field_values",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "field_definition_id",
            sa.Integer(),
            sa.ForeignKey("brain_field_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "field_definition_id", name="uq_tenant_brain_field_values_tenant_field"),
    )
    op.create_index(op.f("ix_tenant_brain_field_values_tenant_id"), "tenant_brain_field_values", ["tenant_id"], unique=False)
    op.create_index(
        op.f("ix_tenant_brain_field_values_field_definition_id"),
        "tenant_brain_field_values",
        ["field_definition_id"],
        unique=False,
    )

    op.create_table(
        "action_items",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("responsible_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_action_items_tenant_id"), "action_items", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_action_items_created_at"), "action_items", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_action_items_created_at"), table_name="action_items")
    op.drop_index(op.f("ix_action_items_tenant_id"), table_name="action_items")
    op.drop_table("action_items")

    op.drop_index(op.f("ix_tenant_brain_field_values_field_definition_id"), table_name="tenant_brain_field_values")
    op.drop_index(op.f("ix_tenant_brain_field_values_tenant_id"), table_name="tenant_brain_field_values")
    op.drop_table("tenant_brain_field_values")

    op.drop_index(op.f("ix_brain_field_definitions_key"), table_name="brain_field_definitions")
    op.drop_table("brain_field_definitions")
