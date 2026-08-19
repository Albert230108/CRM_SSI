"""add ai_auto_draft_approval_requests table

Revision ID: 0047_add_ai_auto_draft_approval_requests
Revises: 0046_split_planner_auto_mode
Create Date: 2026-08-19 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0047_add_ai_auto_draft_approval_requests"
down_revision = "0046_split_planner_auto_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_auto_draft_approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ai_auto_draft_id",
            sa.Integer(),
            sa.ForeignKey("ai_auto_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(length=100), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.String(length=10), nullable=True),
        sa.UniqueConstraint("ai_auto_draft_id", "user_id", name="uq_ai_auto_draft_approval_request_draft_user"),
    )
    op.create_index(
        "ix_ai_auto_draft_approval_requests_ai_auto_draft_id",
        "ai_auto_draft_approval_requests",
        ["ai_auto_draft_id"],
    )
    op.create_index(
        "ix_ai_auto_draft_approval_requests_user_id",
        "ai_auto_draft_approval_requests",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_auto_draft_approval_requests_user_id", table_name="ai_auto_draft_approval_requests")
    op.drop_index("ix_ai_auto_draft_approval_requests_ai_auto_draft_id", table_name="ai_auto_draft_approval_requests")
    op.drop_table("ai_auto_draft_approval_requests")
