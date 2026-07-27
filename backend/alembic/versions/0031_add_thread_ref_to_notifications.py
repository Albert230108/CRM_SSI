"""add thread_ref to notifications

Revision ID: 0031_add_thread_ref_to_notifications
Revises: 0030_add_guidelines_to_ai_reply_templates
Create Date: 2026-07-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0031_add_thread_ref_to_notifications"
down_revision = "0030_add_guidelines_to_ai_reply_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("thread_ref", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "thread_ref")
