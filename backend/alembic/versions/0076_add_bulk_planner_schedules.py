"""add bulk planner schedules

Revision ID: 0076_add_bulk_planner_schedules
Revises: 0075_action_items_tenant_id_nullable
Create Date: 2026-08-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0076_add_bulk_planner_schedules"
down_revision = "0075_action_items_tenant_id_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bulk_planner_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("run_time_local", sa.Time(), nullable=False),
        sa.Column("status_filter", sa.JSON(), nullable=True),
        sa.Column("last_message_within_days", sa.Integer(), nullable=True),
        sa.Column("last_message_direction", sa.String(length=20), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bulk_planner_schedules_id"), "bulk_planner_schedules", ["id"], unique=False)
    op.create_index(op.f("ix_bulk_planner_schedules_next_run_at"), "bulk_planner_schedules", ["next_run_at"], unique=False)

    op.create_table(
        "bulk_planner_schedule_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_reason", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("matched_tenant_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.ForeignKeyConstraint(["schedule_id"], ["bulk_planner_schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bulk_planner_schedule_runs_id"), "bulk_planner_schedule_runs", ["id"], unique=False)
    op.create_index(op.f("ix_bulk_planner_schedule_runs_schedule_id"), "bulk_planner_schedule_runs", ["schedule_id"], unique=False)

    op.create_table(
        "bulk_planner_schedule_run_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("draft_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["draft_id"], ["ai_auto_drafts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["bulk_planner_schedule_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bulk_planner_schedule_run_results_id"), "bulk_planner_schedule_run_results", ["id"], unique=False)
    op.create_index(op.f("ix_bulk_planner_schedule_run_results_run_id"), "bulk_planner_schedule_run_results", ["run_id"], unique=False)
    op.create_index(op.f("ix_bulk_planner_schedule_run_results_tenant_id"), "bulk_planner_schedule_run_results", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bulk_planner_schedule_run_results_tenant_id"), table_name="bulk_planner_schedule_run_results")
    op.drop_index(op.f("ix_bulk_planner_schedule_run_results_run_id"), table_name="bulk_planner_schedule_run_results")
    op.drop_index(op.f("ix_bulk_planner_schedule_run_results_id"), table_name="bulk_planner_schedule_run_results")
    op.drop_table("bulk_planner_schedule_run_results")

    op.drop_index(op.f("ix_bulk_planner_schedule_runs_schedule_id"), table_name="bulk_planner_schedule_runs")
    op.drop_index(op.f("ix_bulk_planner_schedule_runs_id"), table_name="bulk_planner_schedule_runs")
    op.drop_table("bulk_planner_schedule_runs")

    op.drop_index(op.f("ix_bulk_planner_schedules_next_run_at"), table_name="bulk_planner_schedules")
    op.drop_index(op.f("ix_bulk_planner_schedules_id"), table_name="bulk_planner_schedules")
    op.drop_table("bulk_planner_schedules")
