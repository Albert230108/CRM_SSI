from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.api.gmail_integration import sync_email_across_gmail_accounts
from app.models.tenant import Tenant
from app.services.background_jobs import start_job
from app.services.tenant_conversation_links import remove_conversations_for_matched_email

logger = logging.getLogger(__name__)


def handle_tenant_email_change(db: Session, tenant: Tenant, old_email: str | None, new_email: str | None) -> None:
    """Reconcile Gmail conversation links when a Beds24 booking's guest email changes.

    Beds24 resyncs (scheduled sync, webhooks, and admin "sync all") overwrite Tenant.email
    directly with whatever the booking currently has, with no chance for a human to confirm the
    change the way the manual email-link UI does. So on any actual change this mirrors that UI's
    disconnect/resync behavior automatically: the old address's conversations are detached (same
    "unlink if shared, delete if not" rule as manually unlinking an email), and a Gmail history
    sync is kicked off for the new address so its past messages surface without waiting on the
    next scheduled poll.
    """
    if not old_email:
        return
    old_normalized = old_email.strip().lower()
    new_normalized = new_email.strip().lower() if new_email else ""
    if old_normalized == new_normalized:
        return

    deleted, unlinked_shared = remove_conversations_for_matched_email(db, tenant.id, old_email)

    gmail_sync_job_id = None
    if new_email:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # start_job schedules the sync via asyncio.create_task, which needs a running loop.
            # Every real caller (webhook handler, admin sync-all job) runs inside one; this only
            # trips for a caller invoking the sync helper directly outside of any event loop
            # (e.g. a script or test), where the resync is skipped rather than crashing the
            # (synchronous, more important) disconnect above.
            logger.warning(
                "tenant_email_changed tenant_id=%s new_email=%s gmail_resync_skipped=no_running_event_loop",
                tenant.id,
                new_email,
            )
        else:
            gmail_sync_job_id = start_job("gmail_sync_email", asyncio.to_thread(sync_email_across_gmail_accounts, new_email))

    logger.info(
        "tenant_email_changed tenant_id=%s old_email=%s new_email=%s deleted_conversations=%s "
        "shared_conversations_unlinked=%s gmail_sync_job_id=%s",
        tenant.id,
        old_email,
        new_email,
        deleted,
        unlinked_shared,
        gmail_sync_job_id,
    )
