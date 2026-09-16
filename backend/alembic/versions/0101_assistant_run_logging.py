"""log assistant chats as agent runs: nullable run tenant + conversation->run link

Revision ID: 0101_assistant_run_logging
Revises: 0100_add_executor_agent
Create Date: 2026-09-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0101_assistant_run_logging"
down_revision = "0100_add_executor_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The floating copilot is per-user and often has no tenant open, but it now records each
    # chat as an AiAgentRun so it shows up in the AI Planner Runs log. Relax the tenant FK so a
    # global (tenant-less) assistant chat can be logged.
    op.alter_column("ai_agent_runs", "tenant_id", existing_type=sa.Integer(), nullable=True)

    # One run per conversation: the first question creates the run, later questions append steps
    # to this same run rather than duplicating it. SET NULL so deleting the run never cascades
    # into the chat.
    op.add_column(
        "assistant_conversations",
        sa.Column(
            "agent_run_id",
            sa.Integer(),
            sa.ForeignKey("ai_agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_assistant_conversations_agent_run_id"),
        "assistant_conversations",
        ["agent_run_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assistant_conversations_agent_run_id"), table_name="assistant_conversations")
    op.drop_column("assistant_conversations", "agent_run_id")
    # Fails if any tenant-less assistant runs exist; that is the expected guard on rolling back.
    op.alter_column("ai_agent_runs", "tenant_id", existing_type=sa.Integer(), nullable=False)
