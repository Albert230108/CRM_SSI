"""add reviewed flag to redo request logs

Revision ID: 0081_add_redo_request_reviewed
Revises: 0080_add_ai_agent_profile_brain_sections_and_redo_overrides
Create Date: 2026-08-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0081_add_redo_request_reviewed"
down_revision = "0080_add_ai_agent_profile_brain_sections_and_redo_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("redo_request_logs", sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("redo_request_logs", "reviewed")
