"""add canonical whatsapp identity columns

Revision ID: 0016_whatsapp_identity_canonicalization
Revises: 0015_whatsapp_outbound_fallback_dedupe
Create Date: 2026-07-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0016_whatsapp_identity_canonicalization"
down_revision = "0015_whatsapp_outbound_fallback_dedupe"
branch_labels = None
depends_on = None


def _normalize_whatsapp_chat_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _normalize_whatsapp_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def upgrade() -> None:
    op.add_column("communications", sa.Column("whatsapp_identity_key", sa.String(length=255), nullable=True))
    op.add_column("communications", sa.Column("whatsapp_normalized_phone", sa.String(length=64), nullable=True))
    op.create_index("ix_communications_whatsapp_identity_key", "communications", ["whatsapp_identity_key"], unique=False)
    op.create_index("ix_communications_whatsapp_normalized_phone", "communications", ["whatsapp_normalized_phone"], unique=False)

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, whatsapp_chat_id FROM communications WHERE whatsapp_chat_id IS NOT NULL")).mappings().all()
    for row in rows:
        raw_chat_id = _normalize_whatsapp_chat_id(row["whatsapp_chat_id"])
        if not raw_chat_id:
            continue
        if raw_chat_id.endswith("@g.us"):
            identity_key = raw_chat_id
            normalized_phone = None
        else:
            base = raw_chat_id.split("@", 1)[0]
            normalized_phone = _normalize_whatsapp_phone(base)
            identity_key = normalized_phone or raw_chat_id
        bind.execute(
            sa.text(
                "UPDATE communications SET whatsapp_identity_key = :identity_key, whatsapp_normalized_phone = :normalized_phone WHERE id = :id"
            ),
            {"id": row["id"], "identity_key": identity_key, "normalized_phone": normalized_phone},
        )


def downgrade() -> None:
    op.drop_index("ix_communications_whatsapp_normalized_phone", table_name="communications")
    op.drop_index("ix_communications_whatsapp_identity_key", table_name="communications")
    op.drop_column("communications", "whatsapp_normalized_phone")
    op.drop_column("communications", "whatsapp_identity_key")
