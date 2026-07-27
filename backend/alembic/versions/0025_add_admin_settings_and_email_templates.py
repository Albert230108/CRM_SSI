"""add admin_settings and email_templates

Revision ID: 0025_add_admin_settings_and_email_templates
Revises: 0024_add_notification_event_at
Create Date: 2026-07-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_add_admin_settings_and_email_templates"
down_revision = "0024_add_notification_event_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_settings",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("forward_to_email", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_email_templates_user_id"), "email_templates", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_templates_user_id"), table_name="email_templates")
    op.drop_table("email_templates")
    op.drop_table("admin_settings")
