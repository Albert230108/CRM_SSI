"""add floating CRM copilot: knowledge base, saved conversations, assistant agent profile

Revision ID: 0099_add_ai_assistant
Revises: 0098_add_finance_line_breakdown
Create Date: 2026-09-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0099_add_ai_assistant"
down_revision = "0098_add_finance_line_breakdown"
branch_labels = None
depends_on = None


_ASSISTANT_INSTRUCTIONS = (
    "You are the in-app copilot for staff using this short-stay rental CRM. Help them find "
    "where a feature lives, understand how a workflow works, and look up live tenant/booking "
    "data when asked. Ground every answer in the context you're given or the tools you're "
    "offered - never invent a screen, a setting, or a data value that isn't there."
)


def upgrade() -> None:
    op.create_table(
        "app_knowledge_entries",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="user"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="New chat"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_trace", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
    )

    # Seed a single default assistant profile so the feature works out of the box, the way an
    # admin would create one in the AI Agent Profiles UI. Only inserted when none exists yet.
    profiles = sa.table(
        "ai_agent_profiles",
        sa.column("name", sa.String),
        sa.column("role", sa.String),
        sa.column("is_default", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("instructions", sa.Text),
        sa.column("prompt_blocks", sa.JSON),
        sa.column("escalate_keywords", sa.JSON),
    )
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT COUNT(*) FROM ai_agent_profiles WHERE role = 'assistant'")
    ).scalar()
    if not existing:
        op.bulk_insert(
            profiles,
            [
                {
                    "name": "Default assistant",
                    "role": "assistant",
                    "is_default": True,
                    "is_active": True,
                    "instructions": _ASSISTANT_INSTRUCTIONS,
                    "prompt_blocks": {},
                    "escalate_keywords": [],
                }
            ],
        )


def downgrade() -> None:
    op.execute("DELETE FROM ai_agent_profiles WHERE role = 'assistant'")
    op.drop_table("assistant_messages")
    op.drop_table("assistant_conversations")
    op.drop_table("app_knowledge_entries")
