"""add executor agent: profile pin/mode, pending_execution rename, path-based quotation attachment

The executor is the only role that ever writes to Beds24 - it judges a Beds24 write the sales
manager prepared locally (an invoice-item update or a brand-new booking) against the operator's
own natural-language rules (its profile.instructions), then applies it if approved. The sales
manager no longer stages a Beds24 update itself, so ai_auto_drafts.pending_beds24_update is
renamed to pending_execution (same JSON shape family, now discriminated by an "action" key) and
gains an executor_run_id link to the AiAgentRun that judged it.

The quotation PDF attachment also moves from stored bytes (quotation_attachment_id, a
CommunicationAttachment) to a path reference (quotation_file_path/quotation_filename) resolved
lazily at send time against the shared TENANT_FILES_ROOT mount - quotation_attachment_id is kept
for backward compatibility with drafts created before this change.

Revision ID: 0100_add_executor_agent
Revises: 0099_add_ai_assistant
Create Date: 2026-09-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0100_add_executor_agent"
down_revision = "0099_add_ai_assistant"
branch_labels = None
depends_on = None


_EXECUTOR_INSTRUCTIONS = (
    "You are the executor for a short-stay rental CRM. The sales manager has prepared a Beds24 "
    "write - either an updated invoice-item set for an existing booking, or a brand-new booking - "
    "built entirely from figures the pricing engine already computed. Approve a Beds24 push only "
    "when: the quote total is positive and internally consistent; the check-in/check-out dates "
    "are valid and consistent with the invoice items; the guest has explicitly accepted the price "
    "in the conversation; and there are no refund, dispute, or cancellation keywords involved. "
    "Otherwise block the action and explain exactly why in `reason`."
)


def upgrade() -> None:
    op.add_column(
        "tenant_ai_settings",
        sa.Column("executor_profile_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenant_ai_settings_executor_profile",
        "tenant_ai_settings",
        "ai_agent_profiles",
        ["executor_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "tenant_ai_settings",
        sa.Column("executor_mode", sa.String(length=12), nullable=True),
    )

    op.add_column(
        "admin_settings",
        sa.Column("executor_default_mode", sa.String(length=12), nullable=False, server_default="manual"),
    )

    op.alter_column(
        "ai_auto_drafts",
        "pending_beds24_update",
        new_column_name="pending_execution",
    )
    op.add_column(
        "ai_auto_drafts",
        sa.Column("executor_run_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ai_auto_drafts_executor_run",
        "ai_auto_drafts",
        "ai_agent_runs",
        ["executor_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "ai_auto_drafts",
        sa.Column("quotation_file_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "ai_auto_drafts",
        sa.Column("quotation_filename", sa.String(length=255), nullable=True),
    )

    # Seed a single default executor profile so the feature works out of the box, the way an
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
        sa.text("SELECT COUNT(*) FROM ai_agent_profiles WHERE role = 'executor'")
    ).scalar()
    if not existing:
        op.bulk_insert(
            profiles,
            [
                {
                    "name": "Default executor",
                    "role": "executor",
                    "is_default": True,
                    "is_active": True,
                    "instructions": _EXECUTOR_INSTRUCTIONS,
                    "prompt_blocks": {},
                    "escalate_keywords": [],
                }
            ],
        )


def downgrade() -> None:
    op.execute("DELETE FROM ai_agent_profiles WHERE role = 'executor'")

    op.drop_column("ai_auto_drafts", "quotation_filename")
    op.drop_column("ai_auto_drafts", "quotation_file_path")
    op.drop_constraint("fk_ai_auto_drafts_executor_run", "ai_auto_drafts", type_="foreignkey")
    op.drop_column("ai_auto_drafts", "executor_run_id")
    op.alter_column(
        "ai_auto_drafts",
        "pending_execution",
        new_column_name="pending_beds24_update",
    )

    op.drop_column("admin_settings", "executor_default_mode")

    op.drop_column("tenant_ai_settings", "executor_mode")
    op.drop_constraint(
        "fk_tenant_ai_settings_executor_profile", "tenant_ai_settings", type_="foreignkey"
    )
    op.drop_column("tenant_ai_settings", "executor_profile_id")
