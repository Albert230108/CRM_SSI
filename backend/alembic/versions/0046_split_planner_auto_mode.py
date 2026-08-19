"""split planner_mode 'auto' into 'auto-draft' and 'auto-send'

Revision ID: 0046_split_planner_auto_mode
Revises: 0045_add_pinned_tenant_ids
Create Date: 2026-08-19 00:00:00.000000
"""
from alembic import op


revision = "0046_split_planner_auto_mode"
down_revision = "0045_add_pinned_tenant_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Data-only: preserve today's behaviour for every tenant already on "auto" by mapping it to
    # the new "auto-send" value, which keeps the same planner-loop-plus-scheduled-send semantics.
    # Columns are already String(10), which fits both new values, so no schema change is needed.
    op.execute("UPDATE tenant_ai_settings SET planner_mode = 'auto-send' WHERE planner_mode = 'auto'")
    op.execute("UPDATE admin_settings SET planner_default_mode = 'auto-send' WHERE planner_default_mode = 'auto'")


def downgrade() -> None:
    op.execute(
        "UPDATE tenant_ai_settings SET planner_mode = 'auto' WHERE planner_mode IN ('auto-draft', 'auto-send')"
    )
    op.execute(
        "UPDATE admin_settings SET planner_default_mode = 'auto' WHERE planner_default_mode IN ('auto-draft', 'auto-send')"
    )
