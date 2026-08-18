"""add ai agent profiles and planner mode settings

Revision ID: 0038_add_ai_agent_profiles
Revises: 0037_add_brain_sections
Create Date: 2026-08-18 00:00:01.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0038_add_ai_agent_profiles"
down_revision = "0037_add_brain_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("history_limit", sa.Integer(), server_default="40", nullable=False),
        sa.Column("history_channels", sa.String(length=20), server_default="both", nullable=False),
        sa.Column("history_lookback_days", sa.Integer(), nullable=True),
        sa.Column("include_beds24", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("include_payments", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("include_notes", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("include_brain_index", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("match_inbound_language", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("escalate_keywords", sa.JSON(), nullable=False),
        sa.Column("on_no_template_match", sa.String(length=20), server_default="escalate", nullable=False),
        sa.Column("min_confidence", sa.Float(), server_default="0.5", nullable=False),
        sa.Column("max_redraft_attempts", sa.Integer(), server_default="2", nullable=False),
        sa.Column("block_auto_send_on_fail", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("daily_token_cap", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_agent_profiles_role"), "ai_agent_profiles", ["role"])

    op.add_column(
        "tenant_ai_settings",
        sa.Column("planner_mode", sa.String(length=10), server_default="off", nullable=False),
    )
    op.add_column("tenant_ai_settings", sa.Column("planner_profile_id", sa.Integer(), nullable=True))
    op.add_column("tenant_ai_settings", sa.Column("checker_profile_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tenant_ai_settings_planner_profile",
        "tenant_ai_settings",
        "ai_agent_profiles",
        ["planner_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tenant_ai_settings_checker_profile",
        "tenant_ai_settings",
        "ai_agent_profiles",
        ["checker_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "admin_settings",
        sa.Column("planner_default_mode", sa.String(length=10), server_default="off", nullable=False),
    )
    op.add_column("admin_settings", sa.Column("ai_daily_token_cap", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_settings", "ai_daily_token_cap")
    op.drop_column("admin_settings", "planner_default_mode")
    op.drop_constraint("fk_tenant_ai_settings_checker_profile", "tenant_ai_settings", type_="foreignkey")
    op.drop_constraint("fk_tenant_ai_settings_planner_profile", "tenant_ai_settings", type_="foreignkey")
    op.drop_column("tenant_ai_settings", "checker_profile_id")
    op.drop_column("tenant_ai_settings", "planner_profile_id")
    op.drop_column("tenant_ai_settings", "planner_mode")
    op.drop_index(op.f("ix_ai_agent_profiles_role"), table_name="ai_agent_profiles")
    op.drop_table("ai_agent_profiles")
