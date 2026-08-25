import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from app.api.admin_invites import router as admin_invites_router
from app.api.admin_settings import router as admin_settings_router
from app.api.action_items import router as action_items_router
from app.api.action_tags import router as action_tags_router
from app.api.admin_sync import router as admin_sync_router
from app.api.ai_agent_profiles import router as ai_agent_profiles_router
from app.api.ai_agent_runs import router as ai_agent_runs_router
from app.api.ai_auto_drafts import router as ai_auto_drafts_router
from app.api.ai_reply_templates import router as ai_reply_templates_router
from app.api.auth import router as auth_router
from app.api.beds24_availability import router as beds24_availability_router
from app.api.beds24_webhooks import router as beds24_webhook_router
from app.api.brain_fields import router as brain_fields_router
from app.api.brain_sections import router as brain_sections_router
from app.api.communications import router as communications_router
from app.api.communication_attachments import router as communication_attachments_router
from app.api.email_templates import router as email_templates_router
from app.api.gmail_integration import _catch_up_gmail_account, _start_watch
from app.api.gmail_integration import router as gmail_integration_router
from app.api.invites import router as invites_router
from app.api.memory_qa import router as memory_qa_router
from app.api.memory_suggestions import router as memory_suggestions_router
from app.api.notifications import router as notifications_router
from app.api.quotation import router as quotation_router
from app.api.redo_requests import router as redo_requests_router
from app.api.tenants import router as tenants_router
from app.api.tenant_ai_settings import router as tenant_ai_settings_router
from app.api.tenant_channel_endpoints import router as tenant_channel_endpoints_router
from app.api.users import router as users_router
from app.api.tenant_email_links import router as tenant_email_links_router
from app.api.whatsapp_thread_links import router as whatsapp_thread_links_router
from app.api.working_memory_rules import router as working_memory_rules_router
from app.database import SessionLocal
from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.gmail_integration import GmailAccount
from app.models.tenant_brain_trigger import TenantBrainTrigger
from app.services import action_writer_service, ai_auto_draft_service, beds24_availability_service, tenant_brain_service
from app.services.ai_draft_notification_service import notify_admins_of_new_draft
from app.services.notification_whatsapp_service import flush_due_notification_whatsapp_batch
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
            draft = None
            try:
                draft = ai_auto_draft_service.generate_draft_for_trigger(db, trigger)
            except Exception:
                db.rollback()
                logger.exception("AI auto-draft generation failed trigger_id=%s", trigger_id)
            finally:
                # Always consume the trigger, whether generation succeeded or failed - a
                # permanently-broken trigger (e.g. missing template) must not retry every
                # cycle forever; a new inbound message will register a fresh trigger anyway.
                db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.id == trigger_id).delete()
                db.commit()
            if draft is not None:
                try:
                    notify_admins_of_new_draft(db, draft)
                except Exception:
                    db.rollback()
                    logger.exception("AI draft approval WhatsApp notification failed draft_id=%s", draft.id)
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
                ai_auto_draft_service.send_scheduled_draft(db, draft, resolution_source="auto_timer")
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("AI auto-send failed draft_id=%s", draft_id)
    except Exception:
        logger.exception("AI auto-send scheduler loop failed to load due drafts")
    finally:
        db.close()


def _run_due_tenant_brain_triggers_once() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_triggers = db.query(TenantBrainTrigger).filter(TenantBrainTrigger.trigger_at <= now).all()
        logger.info("Found %s due brain triggers this tick", len(due_triggers))
        for trigger in due_triggers:
            trigger_id = trigger.id
            logger.info("Processing brain trigger %s for tenant %s", trigger_id, trigger.tenant_id)
            try:
                tenant_brain_service.generate_brain_update_for_trigger(db, trigger)
            except Exception:
                db.rollback()
                logger.exception("Tenant brain update generation failed trigger_id=%s", trigger_id)
            finally:
                # Always consume the trigger, whether generation succeeded or failed - a
                # permanently-broken trigger must not retry every cycle forever; a new inbound
                # message will register a fresh trigger anyway.
                db.query(TenantBrainTrigger).filter(TenantBrainTrigger.id == trigger_id).delete()
                db.commit()
    except Exception:
        logger.exception("Tenant brain scheduler loop failed to load due triggers")
    finally:
        db.close()


def _run_due_action_writer_triggers_once() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_triggers = db.query(ActionWriterTrigger).filter(ActionWriterTrigger.trigger_at <= now).all()
        logger.info("Found %s due action writer triggers this tick", len(due_triggers))
        for trigger in due_triggers:
            trigger_id = trigger.id
            logger.info("Processing action writer trigger %s for tenant %s", trigger_id, trigger.tenant_id)
            try:
                action_writer_service.generate_action_writer_update_for_trigger(db, trigger)
            except Exception:
                db.rollback()
                logger.exception("Action writer update generation failed trigger_id=%s", trigger_id)
            finally:
                # Always consume the trigger, whether generation succeeded or failed - a
                # permanently-broken trigger must not retry every cycle forever; a new message
                # will register a fresh trigger anyway.
                db.query(ActionWriterTrigger).filter(ActionWriterTrigger.id == trigger_id).delete()
                db.commit()
    except Exception:
        logger.exception("Action writer scheduler loop failed to load due triggers")
    finally:
        db.close()


def _run_due_notification_whatsapp_batch_once() -> None:
    db = SessionLocal()
    try:
        flush_due_notification_whatsapp_batch(db)
    except Exception:
        db.rollback()
        logger.exception("Notification WhatsApp batch flush failed")
    finally:
        db.close()


BEDS24_AVAILABILITY_REFRESH_INTERVAL_SECONDS = int(os.getenv("BEDS24_AVAILABILITY_REFRESH_INTERVAL_SECONDS", str(30 * 60)))
_last_beds24_availability_refresh: datetime | None = None


async def _maybe_refresh_beds24_availability_once() -> None:
    """Runs at most once per BEDS24_AVAILABILITY_REFRESH_INTERVAL_SECONDS, piggybacking on the
    fast AI-draft scheduler tick rather than a separate loop. The actual overlap guard against a
    slow-running fetch is beds24_availability_service's own `_is_running` flag - this timestamp
    check is only about not re-checking on every 15-second tick.
    """
    global _last_beds24_availability_refresh
    now = datetime.now(timezone.utc)
    if (
        _last_beds24_availability_refresh is not None
        and (now - _last_beds24_availability_refresh).total_seconds() < BEDS24_AVAILABILITY_REFRESH_INTERVAL_SECONDS
    ):
        return
    _last_beds24_availability_refresh = now
    db = SessionLocal()
    try:
        await beds24_availability_service.refresh_availability_summary(db)
    except Exception:
        logger.exception("Beds24 availability refresh failed")
    finally:
        db.close()


async def _ai_draft_scheduler_forever() -> None:
    while True:
        await asyncio.sleep(AI_DRAFT_SCHEDULER_INTERVAL_SECONDS)
        await asyncio.to_thread(_run_due_ai_draft_triggers_once)
        await asyncio.to_thread(_run_due_ai_auto_sends_once)
        await asyncio.to_thread(_run_due_tenant_brain_triggers_once)
        await asyncio.to_thread(_run_due_action_writer_triggers_once)
        await asyncio.to_thread(_run_due_notification_whatsapp_batch_once)
        await _maybe_refresh_beds24_availability_once()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("app").setLevel(logging.INFO)
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
app.include_router(brain_sections_router, prefix="/api")
app.include_router(tenant_ai_settings_router, prefix="/api")
app.include_router(ai_auto_drafts_router, prefix="/api")
app.include_router(ai_agent_profiles_router, prefix="/api")
app.include_router(ai_agent_runs_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(gmail_integration_router)
app.include_router(tenants_router, prefix="/api")
app.include_router(quotation_router, prefix="/api")
app.include_router(tenant_channel_endpoints_router, prefix="/api")
app.include_router(whatsapp_thread_links_router, prefix="/api")
app.include_router(tenant_email_links_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(beds24_webhook_router, prefix="/api")
app.include_router(beds24_availability_router, prefix="/api")
app.include_router(brain_fields_router, prefix="/api")
app.include_router(action_items_router, prefix="/api")
app.include_router(action_tags_router, prefix="/api")
app.include_router(working_memory_rules_router, prefix="/api")
app.include_router(memory_suggestions_router, prefix="/api")
app.include_router(memory_qa_router, prefix="/api")
app.include_router(redo_requests_router, prefix="/api")
app.include_router(whatsapp_webhook_router)
app.include_router(gmail_webhook_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
