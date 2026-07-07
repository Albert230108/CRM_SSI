"""add whatsapp outbound fallback dedupe constraint

Revision ID: 0015_whatsapp_outbound_fallback_dedupe
Revises: 0014_communication_whatsapp_account_metadata
Create Date: 2026-07-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0015_whatsapp_outbound_fallback_dedupe"
down_revision = "0014_communication_whatsapp_account_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_communications_tenant_whatsapp_chat_account",
        "communications",
        ["tenant_id", "channel", "direction", "whatsapp_chat_id", "external_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_communications_tenant_whatsapp_chat_account", table_name="communications")
