"""default include_payments on for existing action_writer profiles

Revision ID: 0069_default_action_writer_payments
Revises: 0068_add_availability_context_note
Create Date: 2026-08-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0069_default_action_writer_payments"
down_revision = "0068_add_availability_context_note"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE ai_agent_profiles SET include_payments = true WHERE role = 'action_writer'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE ai_agent_profiles SET include_payments = false WHERE role = 'action_writer'"
        )
    )
