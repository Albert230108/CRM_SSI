"""add tenant conversation links

Revision ID: 0023_add_tenant_conversation_links
Revises: 0022_add_notifications
Create Date: 2026-07-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_add_tenant_conversation_links"
down_revision = "0022_add_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_conversation_links",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="email_match"),
        sa.Column("matched_email", sa.String(length=255), nullable=True),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_tenant_conversation_links_tenant_id"), "tenant_conversation_links", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_conversation_links_conversation_id"), "tenant_conversation_links", ["conversation_id"], unique=False)

    # Uniqueness only applies to currently-active links so a tenant can be relinked
    # to the same conversation later without violating the constraint.
    op.execute(
        "CREATE UNIQUE INDEX uq_tenant_conversation_links_active "
        "ON tenant_conversation_links (tenant_id, conversation_id) "
        "WHERE unlinked_at IS NULL"
    )

    # Backfill: every conversation that already has a tenant_id gets a link to that tenant,
    # so existing single-tenant assignments keep working immediately after migration.
    op.execute(
        "INSERT INTO tenant_conversation_links (tenant_id, conversation_id, source, created_at, updated_at) "
        "SELECT tenant_id, id, 'backfill', now(), now() FROM conversations WHERE tenant_id IS NOT NULL"
    )

    # Also backfill: link any OTHER tenant that shares the same email address as a conversation's
    # participants, so tenants who were previously "stolen from" regain visibility immediately.
    op.execute(
        """
        INSERT INTO tenant_conversation_links (tenant_id, conversation_id, source, matched_email, created_at, updated_at)
        SELECT DISTINCT t.id, cm.conversation_id, 'backfill_email_match', t.email, now(), now()
        FROM conversation_messages cm
        JOIN tenants t
          ON t.email IS NOT NULL
         AND (t.email = cm.sender_email OR t.email = cm.recipient_email)
        WHERE NOT EXISTS (
            SELECT 1 FROM tenant_conversation_links tcl
            WHERE tcl.tenant_id = t.id AND tcl.conversation_id = cm.conversation_id AND tcl.unlinked_at IS NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_tenant_conversation_links_active")
    op.drop_index(op.f("ix_tenant_conversation_links_conversation_id"), table_name="tenant_conversation_links")
    op.drop_index(op.f("ix_tenant_conversation_links_tenant_id"), table_name="tenant_conversation_links")
    op.drop_table("tenant_conversation_links")
