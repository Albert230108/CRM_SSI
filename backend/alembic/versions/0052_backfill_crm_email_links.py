"""backfill tenant.email into CRM_EMAIL links

CRM_EMAIL links (tenant_email_addresses) are now the only authoritative source of a tenant's
email address: Beds24's main guest email is no longer written to tenants.email, and neither
Gmail matching nor the sync search query reads that column any more.

Without this backfill every tenant whose only address lived in tenants.email would silently
stop matching inbound mail the moment that change ships. This copies each such address into an
active link so existing tenants keep working unchanged.

Deliberately local-only: no Beds24 API calls are made, so nothing is written back to any
booking. Rows are marked source="beds24_backfill" / beds24_sync_status="not_synced" so an
operator can see which links have never been pushed to Beds24 and push them from the
"Manage emails" UI.

Revision ID: 0052_backfill_crm_email_links
Revises: 0051_add_tenant_brain
Create Date: 2026-08-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0052_backfill_crm_email_links"
down_revision = "0051_add_tenant_brain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Only tenants that have a usable address and no active link for it already, so re-running
    # this (or running it after an operator has linked addresses by hand) can't duplicate rows.
    rows = connection.execute(
        sa.text(
            """
            SELECT t.id AS tenant_id, TRIM(t.email) AS email
            FROM tenants t
            WHERE t.email IS NOT NULL
              AND TRIM(t.email) <> ''
              AND NOT EXISTS (
                  -- Any existing row, active or not: an inactive link means an operator
                  -- deliberately unlinked that address, and a backfill must not resurrect it.
                  SELECT 1 FROM tenant_email_addresses a
                  WHERE a.tenant_id = t.id
                    AND LOWER(a.email) = LOWER(TRIM(t.email))
              )
            """
        )
    ).fetchall()

    for row in rows:
        connection.execute(
            sa.text(
                """
                INSERT INTO tenant_email_addresses
                    (tenant_id, email, beds24_sync_status, source, is_active)
                VALUES (:tenant_id, :email, 'not_synced', 'beds24_backfill', TRUE)
                """
            ),
            {"tenant_id": row.tenant_id, "email": row.email.strip().lower()},
        )


def downgrade() -> None:
    # Only the rows this migration created; hand-made links must survive a downgrade.
    op.execute("DELETE FROM tenant_email_addresses WHERE source = 'beds24_backfill'")
