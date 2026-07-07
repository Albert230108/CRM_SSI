"""add tenant phone aliases

Revision ID: 0017_tenant_phone_aliases
Revises: 0016_whatsapp_identity_canonicalization
Create Date: 2026-07-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0017_tenant_phone_aliases"
down_revision = "0016_whatsapp_identity_canonicalization"
branch_labels = None
depends_on = None


def _normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered.endswith("@c.us"):
        raw = lowered.split("@", 1)[0]
    elif "@" in lowered:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 7 or set(digits) == {"0"}:
        return None
    return digits


def upgrade() -> None:
    op.create_table(
        "tenant_phone_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("normalized_phone", sa.String(length=64), nullable=False),
        sa.Column("raw_phone", sa.String(length=100), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "normalized_phone", name="uq_tenant_phone_aliases_tenant_normalized_phone"),
    )
    op.create_index("ix_tenant_phone_aliases_tenant_id", "tenant_phone_aliases", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_phone_aliases_normalized_phone", "tenant_phone_aliases", ["normalized_phone"], unique=False)

    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id, phone, mobile FROM tenants ORDER BY id ASC")).mappings().all()
    insert_stmt = sa.text(
        "INSERT INTO tenant_phone_aliases (tenant_id, normalized_phone, raw_phone, is_primary, source, created_at, updated_at) "
        "VALUES (:tenant_id, :normalized_phone, :raw_phone, :is_primary, :source, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    for tenant in tenants:
        tenant_id = tenant["id"]
        seen: set[str] = set()
        is_primary = True
        for source, raw_phone in (("tenant.phone", tenant["phone"]), ("tenant.mobile", tenant["mobile"])):
            normalized_phone = _normalize_phone(raw_phone)
            if not normalized_phone or normalized_phone in seen:
                continue
            seen.add(normalized_phone)
            bind.execute(
                insert_stmt,
                {
                    "tenant_id": tenant_id,
                    "normalized_phone": normalized_phone,
                    "raw_phone": str(raw_phone).strip() if raw_phone is not None else normalized_phone,
                    "is_primary": True if is_primary else False,
                    "source": source,
                },
            )
            is_primary = False


def downgrade() -> None:
    op.drop_index("ix_tenant_phone_aliases_normalized_phone", table_name="tenant_phone_aliases")
    op.drop_index("ix_tenant_phone_aliases_tenant_id", table_name="tenant_phone_aliases")
    op.drop_table("tenant_phone_aliases")
