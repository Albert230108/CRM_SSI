"""add guidelines field to ai reply templates

Revision ID: 0030_add_guidelines_to_ai_reply_templates
Revises: 0029_add_tenant_status_filter_to_users
Create Date: 2026-07-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0030_add_guidelines_to_ai_reply_templates"
down_revision = "0029_add_tenant_status_filter_to_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_reply_templates", sa.Column("guidelines", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_reply_templates", "guidelines")
