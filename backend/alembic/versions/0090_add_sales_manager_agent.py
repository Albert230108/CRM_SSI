"""add sales-manager agent: profile pin, quotation attachment link, default profile

Revision ID: 0090_add_sales_manager_agent
Revises: 0089_add_run_qa_messages
Create Date: 2026-09-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0090_add_sales_manager_agent"
down_revision = "0089_add_run_qa_messages"
branch_labels = None
depends_on = None


_SALES_MANAGER_INSTRUCTIONS = (
    "You are the sales manager for a short-stay rental CRM. The planner has asked you to price a "
    "stay and, when requested, produce a full PDF quotation. You are given the planner's requested "
    "parameters (room, dates, guests) and the exact charge lines already computed by the pricing "
    "engine - use those figures verbatim, never invent prices. Write a short, factual price summary "
    "the drafter can weave into the reply, and set a sensible security deposit and any notes the "
    "guest should know."
)


def upgrade() -> None:
    op.add_column(
        "tenant_ai_settings",
        sa.Column("sales_manager_profile_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenant_ai_settings_sales_manager_profile",
        "tenant_ai_settings",
        "ai_agent_profiles",
        ["sales_manager_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "ai_auto_drafts",
        sa.Column("quotation_attachment_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ai_auto_drafts_quotation_attachment",
        "ai_auto_drafts",
        "communication_attachments",
        ["quotation_attachment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Seed a single default sales_manager profile so the feature works out of the box, the way an
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
        sa.text("SELECT COUNT(*) FROM ai_agent_profiles WHERE role = 'sales_manager'")
    ).scalar()
    if not existing:
        op.bulk_insert(
            profiles,
            [
                {
                    "name": "Default sales manager",
                    "role": "sales_manager",
                    "is_default": True,
                    "is_active": True,
                    "instructions": _SALES_MANAGER_INSTRUCTIONS,
                    "prompt_blocks": {},
                    "escalate_keywords": [],
                }
            ],
        )


def downgrade() -> None:
    op.execute("DELETE FROM ai_agent_profiles WHERE role = 'sales_manager'")
    op.drop_constraint(
        "fk_ai_auto_drafts_quotation_attachment", "ai_auto_drafts", type_="foreignkey"
    )
    op.drop_column("ai_auto_drafts", "quotation_attachment_id")
    op.drop_constraint(
        "fk_tenant_ai_settings_sales_manager_profile", "tenant_ai_settings", type_="foreignkey"
    )
    op.drop_column("tenant_ai_settings", "sales_manager_profile_id")
