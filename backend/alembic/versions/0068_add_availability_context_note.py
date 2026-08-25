"""add availability context note and tenant brain flag

Revision ID: 0068_add_availability_context_note
Revises: 0067_add_user_default_accounts
Create Date: 2026-08-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0068_add_availability_context_note"
down_revision = "0067_add_user_default_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "beds24_availability_summary",
        sa.Column("context_note", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "ai_agent_profiles",
        sa.Column("include_tenant_brain", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("ai_agent_profiles", "include_tenant_brain")
    op.drop_column("beds24_availability_summary", "context_note")
