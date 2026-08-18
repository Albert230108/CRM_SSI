"""add ai agent run log and link auto-drafts to it

Revision ID: 0039_add_ai_agent_runs
Revises: 0038_add_ai_agent_profiles
Create Date: 2026-08-18 00:00:02.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0039_add_ai_agent_runs"
down_revision = "0038_add_ai_agent_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("escalation_reason", sa.String(length=60), nullable=True),
        sa.Column("planner_profile_id", sa.Integer(), nullable=True),
        sa.Column("checker_profile_id", sa.Integer(), nullable=True),
        sa.Column("final_template_id", sa.Integer(), nullable=True),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("checker_feedback", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["planner_profile_id"], ["ai_agent_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["checker_profile_id"], ["ai_agent_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["final_template_id"], ["ai_reply_templates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_agent_runs_tenant_id"), "ai_agent_runs", ["tenant_id"])
    op.create_index(op.f("ix_ai_agent_runs_channel"), "ai_agent_runs", ["channel"])
    op.create_index(op.f("ix_ai_agent_runs_status"), "ai_agent_runs", ["status"])
    op.create_index(op.f("ix_ai_agent_runs_created_at"), "ai_agent_runs", ["created_at"])

    op.create_table(
        "ai_agent_run_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("parsed", sa.JSON(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["ai_agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_agent_run_steps_run_id"), "ai_agent_run_steps", ["run_id"])

    op.add_column("ai_auto_drafts", sa.Column("agent_run_id", sa.Integer(), nullable=True))
    op.add_column("ai_auto_drafts", sa.Column("checker_feedback", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_ai_auto_drafts_agent_run",
        "ai_auto_drafts",
        "ai_agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_ai_auto_drafts_agent_run", "ai_auto_drafts", type_="foreignkey")
    op.drop_column("ai_auto_drafts", "checker_feedback")
    op.drop_column("ai_auto_drafts", "agent_run_id")
    op.drop_index(op.f("ix_ai_agent_run_steps_run_id"), table_name="ai_agent_run_steps")
    op.drop_table("ai_agent_run_steps")
    op.drop_index(op.f("ix_ai_agent_runs_created_at"), table_name="ai_agent_runs")
    op.drop_index(op.f("ix_ai_agent_runs_status"), table_name="ai_agent_runs")
    op.drop_index(op.f("ix_ai_agent_runs_channel"), table_name="ai_agent_runs")
    op.drop_index(op.f("ix_ai_agent_runs_tenant_id"), table_name="ai_agent_runs")
    op.drop_table("ai_agent_runs")
