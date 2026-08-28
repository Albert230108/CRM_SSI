"""add bulk planner schedule extra instructions

Revision ID: 0083_add_bulk_planner_schedule_extra_instructions
Revises: 0082_add_email_cc_emails
Create Date: 2026-08-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0083_add_bulk_planner_schedule_extra_instructions"
down_revision = "0082_add_email_cc_emails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bulk_planner_schedules",
        sa.Column("extra_instructions", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bulk_planner_schedules", "extra_instructions")
