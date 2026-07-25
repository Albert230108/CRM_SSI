"""add include_notes to ai reply templates and auto-apply-to-new-tenants admin setting

Revision ID: 0027_add_ai_template_notes_and_auto_apply_setting
Revises: 0026_add_ai_reply_templates_and_ai_settings
Create Date: 2026-07-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0027_add_ai_template_notes_and_auto_apply_setting"
down_revision = "0026_add_ai_reply_templates_and_ai_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_reply_templates", sa.Column("include_notes", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("admin_settings", sa.Column("ai_auto_apply_templates_to_new_tenants", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("admin_settings", "ai_auto_apply_templates_to_new_tenants")
    op.drop_column("ai_reply_templates", "include_notes")
