"""prevent duplicate Gmail conversation rows for the same thread

A sync race (a Pub/Sub push notification landing while the catch-up poller is mid-run against
the same account, or an overlapping manual "Sync All") could previously create two Conversation
rows for the same (provider, provider_account_id, provider_thread_id), since the lookup-or-create
in _upsert_thread had no uniqueness to fall back on. Messages from one Gmail thread could then
end up split across both rows, with whichever row a tenant wasn't linked to never surfacing in
that tenant's timeline -- most visibly, a thread's original message going "missing" while later
replies (upserted after the race window closed) landed on the row that did stay linked.

This merges any such duplicates that already exist before adding a uniqueness constraint that
stops new ones: _upsert_thread's Conversation creation is updated separately (in application
code) to catch the resulting IntegrityError and re-query for whichever row wins the race, instead
of leaving a sync's messages stranded on an orphan.

Only groups with a non-null provider_account_id are considered: new rows always set that column,
so this covers the scope that matters going forward. Rows with a NULL provider_account_id (if
any remain from early data) are left untouched -- ordinary SQL NULL semantics exclude them from
the uniqueness check anyway.

Revision ID: 0053_add_conversation_thread_uniqueness
Revises: 0052_backfill_crm_email_links
Create Date: 2026-08-24 00:00:00.000000
"""
from alembic import op


revision = "0053_add_conversation_thread_uniqueness"
down_revision = "0052_backfill_crm_email_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Map every "loser" duplicate conversation onto the "winner" (lowest id) in its
    # (provider, provider_account_id, provider_thread_id) group. Only groups that actually have
    # more than one row show up here, so this is a no-op on a database with no duplicates yet.
    op.execute(
        """
        CREATE TEMP TABLE conversation_dedup_map AS
        SELECT c.id AS loser_id, w.winner_id
        FROM conversations c
        JOIN (
            SELECT provider, provider_account_id, provider_thread_id, MIN(id) AS winner_id
            FROM conversations
            WHERE provider_account_id IS NOT NULL
            GROUP BY provider, provider_account_id, provider_thread_id
            HAVING COUNT(*) > 1
        ) w
          ON w.provider = c.provider
         AND w.provider_account_id = c.provider_account_id
         AND w.provider_thread_id = c.provider_thread_id
        WHERE c.id <> w.winner_id
        """
    )

    # Every message the race split off onto a loser row moves onto the winner. provider_message_id
    # is globally unique across all conversations, so there's no collision risk here.
    op.execute(
        """
        UPDATE conversation_messages cm
        SET conversation_id = m.winner_id
        FROM conversation_dedup_map m
        WHERE cm.conversation_id = m.loser_id
        """
    )

    # Tenant links on a loser row move onto the winner too, unless the winner already has its own
    # active link for that same tenant (tenant_conversation_links enforces at most one active link
    # per (tenant_id, conversation_id) pair) -- in that case reassigning would violate that
    # constraint, and the winner's existing link already covers it.
    op.execute(
        """
        UPDATE tenant_conversation_links tcl
        SET conversation_id = m.winner_id
        FROM conversation_dedup_map m
        WHERE tcl.conversation_id = m.loser_id
          AND NOT EXISTS (
              SELECT 1 FROM tenant_conversation_links existing
              WHERE existing.conversation_id = m.winner_id
                AND existing.tenant_id = tcl.tenant_id
                AND existing.unlinked_at IS NULL
                AND tcl.unlinked_at IS NULL
          )
        """
    )

    # Any links still pointing at a loser row at this point are redundant (the winner already
    # covers that tenant) or historical/unlinked -- remove them so nothing still references the
    # loser row before it's deleted.
    op.execute(
        """
        DELETE FROM tenant_conversation_links tcl
        USING conversation_dedup_map m
        WHERE tcl.conversation_id = m.loser_id
        """
    )

    op.execute(
        """
        DELETE FROM conversations c
        USING conversation_dedup_map m
        WHERE c.id = m.loser_id
        """
    )

    op.execute("DROP TABLE conversation_dedup_map")

    op.execute(
        "CREATE UNIQUE INDEX uq_conversations_provider_account_thread "
        "ON conversations (provider, provider_account_id, provider_thread_id)"
    )


def downgrade() -> None:
    # The dedup merge above is not meaningfully reversible (there's no record of which duplicate
    # a viewer would have considered "canonical"), so downgrade only removes the constraint.
    op.execute("DROP INDEX IF EXISTS uq_conversations_provider_account_thread")
