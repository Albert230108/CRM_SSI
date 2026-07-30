"""add tenant notes history

Revision ID: 0033_add_tenant_notes_history
Revises: 0032_gmail_account_failure_tracking
Create Date: 2026-07-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0033_add_tenant_notes_history"
down_revision = "0032_gmail_account_failure_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_notes_history",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_tenant_notes_history_tenant_id"), "tenant_notes_history", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_notes_history_changed_at"), "tenant_notes_history", ["changed_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tenant_notes_history_changed_at"), table_name="tenant_notes_history")
    op.drop_index(op.f("ix_tenant_notes_history_tenant_id"), table_name="tenant_notes_history")
    op.drop_table("tenant_notes_history")
