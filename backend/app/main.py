import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from app.api.admin_invites import router as admin_invites_router
from app.api.admin_settings import router as admin_settings_router
from app.api.admin_sync import router as admin_sync_router
from app.api.ai_auto_drafts import router as ai_auto_drafts_router
from app.api.ai_reply_templates import router as ai_reply_templates_router
from app.api.auth import router as auth_router
from app.api.beds24_webhooks import router as beds24_webhook_router
from app.api.communications import router as communications_router
from app.api.communication_attachments import router as communication_attachments_router
from app.api.email_templates import router as email_templates_router
from app.api.gmail_integration import _catch_up_gmail_account, _start_watch
from app.api.gmail_integration import router as gmail_integration_router
from app.api.invites import router as invites_router
from app.api.notifications import router as notifications_router
from app.api.quotation import router as quotation_router
from app.api.tenants import router as tenants_router
from app.api.tenant_ai_settings import router as tenant_ai_settings_router
from app.api.tenant_channel_endpoints import router as tenant_channel_endpoints_router
from app.api.users import router as users_router
from app.api.tenant_email_links import router as tenant_email_links_router
from app.api.whatsapp_thread_links import router as whatsapp_thread_links_router
from app.database import SessionLocal
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.gmail_integration import GmailAccount
from app.services import ai_auto_draft_service
from app.webhooks.gmail import router as gmail_webhook_router
from app.webhooks.whatsapp import router as whatsapp_webhook_router

logger = logging.getLogger(__name__)

EMAIL_POLL_INTERVAL_SECONDS = int(os.getenv("EMAIL_POLL_INTERVAL_SECONDS", "14400"))  # 4 hours
GMAIL_WATCH_RENEWAL_INTERVAL_SECONDS = int(os.getenv("GMAIL_WATCH_RENEWAL_INTERVAL_SECONDS", str(6 * 60 * 60)))
GMAIL_WATCH_RENEWAL_MARGIN = timedelta(hours=24)
# A mailbox with a revoked/expired refresh token fails identically on every catch-up cycle
# forever, with is_active never auto-flipped, so it never surfaces to anyone. After this many
# *consecutive* catch-up failures (~40 hours at the default 4h poll interval - long enough to
# ride out a transient outage) deactivate it so it stops silently burning retries; reconnecting
# is the same manual flow used after an explicit /disconnect.
GMAIL_ACCOUNT_FAILURE_THRESHOLD = int(os.getenv("GMAIL_ACCOUNT_FAILURE_THRESHOLD", "10"))
# Internal poll granularity for the AI auto-draft scheduler - independent of the user-facing
# debounce/auto-send-delay settings (which are typically minutes), just frequent enough that
# those settings feel responsive.
AI_DRAFT_SCHEDULER_INTERVAL_SECONDS = 15


def _poll_gmail_accounts_once() -> None:
    db = SessionLocal()
    try:
        accounts = db.query(GmailAccount).filter(GmailAccount.is_active.is_(True)).order_by(GmailAccount.id.asc()).all()
        for account in accounts:
            account_id = account.id
            try:
                _catch_up_gmail_account(db, account)
                if account.consecutive_failure_count:
                    account.consecutive_failure_count = 0
                    account.last_error_message = None
                    db.commit()
            except Exception as exc:
                # A failed flush/commit leaves the session needing a rollback before any
                # further use, including lazy-loading account.id for this log line — so
                # capture the id above and roll back here, or logging the error itself
                # raises PendingRollbackError and aborts the remaining accounts this cycle.
                db.rollback()
                logger.exception("Background Gmail catch-up failed account_id=%s", account_id)
                account.consecutive_failure_count = (account.consecutive_failure_count or 0) + 1
                account.last_error_message = str(exc)[:1000]
                account.last_failure_at = datetime.now(timezone.utc)
                if account.consecutive_failure_count >= GMAIL_ACCOUNT_FAILURE_THRESHOLD:
                    account.is_active = False
                    logger.error(
                        "Deactivating Gmail account_id=%s after %s consecutive catch-up failures",
                        account_id,
                        account.consecutive_failure_count,
                    )
                db.commit()
    except Exception:
        logger.exception("Background Gmail sync loop failed to load accounts")
    finally:
        db.close()


async def _poll_gmail_accounts_forever() -> None:
    while True:
        await asyncio.sleep(EMAIL_POLL_INTERVAL_SECONDS)
        # _catch_up_gmail_account makes a blocking, synchronous Gmail getProfile call every
        # cycle (cheap - one call, no-op if nothing changed), escalating to the incremental
        # history sync (or, rarely, a full resync) only when the mailbox's historyId has
        # moved since our last cursor. This is a safety net for missed Pub/Sub push
        # notifications, not the primary sync path, hence the long interval. Still blocking,
        # so still routed through asyncio.to_thread — running it inline on the event loop
        # would freeze every concurrent request across the whole app for its duration, and
        # asyncio.to_thread matches the pattern already used for the manual sync-all endpoint
        # in gmail_integration.py.
        await asyncio.to_thread(_poll_gmail_accounts_once)


def _renew_expiring_gmail_watches_once() -> None:
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) + GMAIL_WATCH_RENEWAL_MARGIN
        accounts = (
            db.query(GmailAccount)
            .filter(GmailAccount.is_active.is_(True))
            .filter((GmailAccount.watch_expiration.is_(None)) | (GmailAccount.watch_expiration < cutoff))
            .order_by(GmailAccount.id.asc())
            .all()
        )
        for account in accounts:
            try:
                _start_watch(db, account)
            except Exception:
                logger.exception("Gmail push watch renewal failed account_id=%s", account.id)
    except Exception:
        logger.exception("Gmail push watch renewal loop failed to load accounts")
    finally:
        db.close()


async def _renew_gmail_watches_forever() -> None:
    while True:
        # Gmail watch() registrations expire after ~7 days; renewing on a margin well inside
        # that window means a missed renewal cycle doesn't silently stop push notifications.
        await asyncio.to_thread(_renew_expiring_gmail_watches_once)
        await asyncio.sleep(GMAIL_WATCH_RENEWAL_INTERVAL_SECONDS)


def _run_due_ai_draft_triggers_once() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_triggers = db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.trigger_at <= now).all()
        for trigger in due_triggers:
            trigger_id = trigger.id
            try:
                ai_auto_draft_service.generate_draft_for_trigger(db, trigger)
            except Exception:
                db.rollback()
                logger.exception("AI auto-draft generation failed trigger_id=%s", trigger_id)
            finally:
                # Always consume the trigger, whether generation succeeded or failed - a
                # permanently-broken trigger (e.g. missing template) must not retry every
                # cycle forever; a new inbound message will register a fresh trigger anyway.
                db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.id == trigger_id).delete()
                db.commit()
    except Exception:
        logger.exception("AI auto-draft scheduler loop failed to load due triggers")
    finally:
        db.close()


def _run_due_ai_auto_sends_once() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_drafts = (
            db.query(AiAutoDraft)
            .filter(AiAutoDraft.status == "pending_auto_send", AiAutoDraft.scheduled_send_at <= now)
            .all()
        )
        for draft in due_drafts:
            draft_id = draft.id
            try:
                ai_auto_draft_service.send_scheduled_draft(db, draft)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("AI auto-send failed draft_id=%s", draft_id)
    except Exception:
        logger.exception("AI auto-send scheduler loop failed to load due drafts")
    finally:
        db.close()


async def _ai_draft_scheduler_forever() -> None:
    while True:
        await asyncio.sleep(AI_DRAFT_SCHEDULER_INTERVAL_SECONDS)
        await asyncio.to_thread(_run_due_ai_draft_triggers_once)
        await asyncio.to_thread(_run_due_ai_auto_sends_once)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_poll_gmail_accounts_forever())
    logger.info("Started background Gmail incremental catch-up poll loop interval_seconds=%s", EMAIL_POLL_INTERVAL_SECONDS)
    renewal_task = asyncio.create_task(_renew_gmail_watches_forever())
    logger.info("Started Gmail push watch renewal loop interval_seconds=%s", GMAIL_WATCH_RENEWAL_INTERVAL_SECONDS)
    ai_draft_task = asyncio.create_task(_ai_draft_scheduler_forever())
    logger.info("Started AI auto-draft scheduler loop interval_seconds=%s", AI_DRAFT_SCHEDULER_INTERVAL_SECONDS)
    try:
        yield
    finally:
        task.cancel()
        renewal_task.cancel()
        ai_draft_task.cancel()


app = FastAPI(title="CRM API", redirect_slashes=False, lifespan=lifespan)

resolved_whatsapp_service_url = os.getenv("WHATSAPP_SERVICE_URL", "").strip() or "<unset>"
print(f"[backend] WHATSAPP_SERVICE_URL={resolved_whatsapp_service_url}")

app.include_router(auth_router, prefix="/api")
app.include_router(admin_invites_router, prefix="/api")
app.include_router(admin_settings_router, prefix="/api")
app.include_router(admin_sync_router, prefix="/api")
app.include_router(invites_router, prefix="/api")
app.include_router(communications_router, prefix="/api")
app.include_router(communication_attachments_router, prefix="/api")
app.include_router(email_templates_router, prefix="/api")
app.include_router(ai_reply_templates_router, prefix="/api")
app.include_router(tenant_ai_settings_router, prefix="/api")
app.include_router(ai_auto_drafts_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(gmail_integration_router)
app.include_router(tenants_router, prefix="/api")
app.include_router(quotation_router, prefix="/api")
app.include_router(tenant_channel_endpoints_router, prefix="/api")
app.include_router(whatsapp_thread_links_router, prefix="/api")
app.include_router(tenant_email_links_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(beds24_webhook_router, prefix="/api")
app.include_router(whatsapp_webhook_router)
app.include_router(gmail_webhook_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
