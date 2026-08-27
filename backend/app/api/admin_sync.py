from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import asyncio
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.gmail_integration import _sync_gmail_account, sync_email_across_gmail_accounts
from app.api.tenants import _extract_guest_fields
from app.core.dependencies import get_current_admin_user, get_current_user, get_db
from app.database import SessionLocal
from app.models.gmail_integration import GmailAccount
from app.models.tenant import Tenant
from app.models.user import User
from app.services.background_jobs import cancel_job, find_running_job, get_job, start_job, update_job_progress
from app.services.beds24_client import get_bookings
from app.services.tenant_email_sync import sync_tenant_email_addresses_from_beds24
from app.services.tenant_notes_history import SOURCE_BEDS24_SYNC_ALL, set_tenant_notes
from app.services.tenant_phone_aliases import sync_tenant_phone_aliases
from app.services.thread_timeline_service import build_tenant_thread_timeline
from app.services.whatsapp_chat_directory import resync_whatsapp_chat

router = APIRouter(prefix="/admin", tags=["admin-sync"])
logger = logging.getLogger(__name__)


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _update_tenant_from_beds24(db: Session, tenant: Tenant, booking: dict[str, Any], changed_by_user_id: int | None = None) -> list[str]:
    fields = _extract_guest_fields(booking)
    tenant.first_name = fields.get("first_name") or tenant.first_name
    tenant.last_name = fields.get("last_name") or tenant.last_name
    # Beds24's main guest email is no longer authoritative: it is whatever address the OTA
    # forwarded, which is frequently an alias that never reaches the guest. The CRM_EMAIL info
    # items are the single source of truth now, so this sync reconciles those instead of
    # touching tenant.email. get_bookings() already requested includeInfoItems=true, so this
    # costs no extra round-trip. Previously only the live webhook did this, which meant a
    # CRM_EMAIL added in Beds24 never reached the CRM outside a booking event.
    info_items = booking.get("infoItems")
    newly_linked_emails: list[str] = []
    if isinstance(info_items, list):
        newly_linked_emails = sync_tenant_email_addresses_from_beds24(db, tenant, info_items)
    tenant.phone = fields.get("phone") or tenant.phone
    tenant.mobile = fields.get("mobile") or tenant.mobile
    tenant.check_in = fields.get("check_in") or tenant.check_in
    tenant.check_out = fields.get("check_out") or tenant.check_out
    tenant.city = fields.get("city") or tenant.city
    tenant.country = fields.get("country") or tenant.country
    tenant.zip_code = fields.get("zip_code") or tenant.zip_code
    tenant.address = fields.get("address") or tenant.address
    tenant.company = fields.get("company") or tenant.company
    tenant.language = fields.get("language") or tenant.language
    tenant.num_adults = fields.get("num_adults") or tenant.num_adults
    tenant.num_children = fields.get("num_children") or tenant.num_children
    tenant.num_nights = fields.get("num_nights") or tenant.num_nights
    tenant.arrival_time = fields.get("arrival_time") or tenant.arrival_time
    tenant.departure_time = fields.get("departure_time") or tenant.departure_time
    tenant.room_name = fields.get("room_name") or tenant.room_name
    tenant.source = fields.get("source") or tenant.source
    tenant.referer = fields.get("referer") or tenant.referer
    tenant.total_price = fields.get("total_price") or tenant.total_price
    tenant.commission = fields.get("commission") or tenant.commission
    tenant.deposit = fields.get("deposit") or tenant.deposit
    tenant.currency = fields.get("currency") or tenant.currency
    set_tenant_notes(db, tenant, fields.get("notes"), source=SOURCE_BEDS24_SYNC_ALL, changed_by_user_id=changed_by_user_id)
    tenant.booking_status = fields.get("booking_status") or tenant.booking_status
    tenant.responsible_comm = fields.get("responsible_comm") or tenant.responsible_comm
    tenant.name = fields.get("name") or tenant.name
    tenant.beds24_raw = booking
    room_id = fields.get("room_id")
    tenant.room_id = room_id if room_id is not None else tenant.room_id
    sync_tenant_phone_aliases(db, tenant, primary_phone=tenant.phone, alias_phones=[tenant.mobile])
    return newly_linked_emails


async def _sync_beds24(db: Session, changed_by_user_id: int | None = None, tenant_ids: list[int] | None = None) -> int:
    updated = 0
    newly_linked_emails: list[str] = []
    bookings = await get_bookings()
    for booking in bookings:
        booking_id = str(booking.get("id") or "").strip()
        if not booking_id:
            continue

        tenant_query = db.query(Tenant).filter(Tenant.booking_id == booking_id)
        if tenant_ids is not None:
            tenant_query = tenant_query.filter(Tenant.id.in_(tenant_ids))
        tenant = tenant_query.first()
        if tenant is None:
            continue

        # No per-booking detail re-fetch: get_bookings() already requested includeInfoItems=true,
        # so each list item carries the same fields the single-booking endpoint would return.
        # Re-fetching cost one sequential HTTPS round-trip per tenant for identical data.
        newly_linked_emails.extend(
            _update_tenant_from_beds24(
                db,
                tenant,
                booking,
                changed_by_user_id=changed_by_user_id,
            )
        )
        updated += 1
    db.commit()

    # Search Gmail history for any address a CRM_EMAIL reconciliation above just linked, so past
    # messages surface in the tenant's thread instead of only future ones. Fired once after the
    # commit above (not per-tenant mid-loop) so the background jobs' own DB sessions can see the
    # new links, and so this loop's existing single-commit transaction shape is unchanged.
    for email in newly_linked_emails:
        start_job("gmail_sync_email", asyncio.to_thread(sync_email_across_gmail_accounts, email))

    return updated


async def _sync_emails(
    db: Session,
    tenant_ids: list[int] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    accounts = db.query(GmailAccount).filter(GmailAccount.is_active.is_(True)).order_by(GmailAccount.id.asc()).all()
    imported = 0
    if progress is not None:
        progress(0, len(accounts))
    for index, account in enumerate(accounts, start=1):
        # _sync_gmail_account makes blocking, synchronous Gmail API calls (up to 100 threads
        # per account) with no yield points of its own. Looping it inline here would monopolize
        # this worker's event loop for every other concurrent request until all accounts finished.
        imported += await run_in_threadpool(_sync_gmail_account_in_fresh_session, account.id, tenant_ids)
        # Reported per account rather than per thread: this is the longest phase by far, and
        # without any counter the overlay sat on a frozen bar for its whole duration, which is
        # indistinguishable from being stuck.
        if progress is not None:
            progress(index, len(accounts))
    return imported


async def _sync_whatsapp_linked_endpoints(db: Session, tenant_ids: list[int] | None = None) -> dict[str, Any]:
    """Sync WhatsApp history for all manually linked endpoints.

    Mirrors the per-chat "Resync full history" action in Manage Chats exactly: it calls the
    same resync_whatsapp_chat() service function (so it honors WHATSAPP_SERVICE_URL_MAP
    per-account routing instead of a single global URL) and runs the same post-resync
    Communication.external_chat_namespace reconciliation, just looped over every linked chat.
    """
    from app.models.communication import Communication
    from app.models.tenant_channel_endpoint import TenantChannelEndpoint
    from app.services.whatsapp_client import WHATSAPP_API_KEY, WHATSAPP_SERVICE_URL, WHATSAPP_SERVICE_URL_MAP

    if not WHATSAPP_API_KEY or not (WHATSAPP_SERVICE_URL or WHATSAPP_SERVICE_URL_MAP):
        return {
            "synced_endpoints": 0,
            "total_imported": 0,
            "results": [],
            "errors": [],
        }

    # Find all active WhatsApp endpoints with manual links (external_chat_namespace set)
    endpoint_query = db.query(TenantChannelEndpoint).filter(
        TenantChannelEndpoint.channel_type == "whatsapp",
        TenantChannelEndpoint.is_active.is_(True),
        TenantChannelEndpoint.external_chat_namespace.isnot(None),
    )
    if tenant_ids is not None:
        endpoint_query = endpoint_query.filter(TenantChannelEndpoint.tenant_id.in_(tenant_ids))
    active_links = endpoint_query.all()

    results = []
    errors = []
    total_imported = 0

    for endpoint in active_links:
        try:
            print(
                f"[crm] whatsapp endpoint sync request endpoint_id={endpoint.id} chat_id={endpoint.external_chat_namespace} external_account_id={endpoint.external_account_id}"
            )
            sync_result = await resync_whatsapp_chat(endpoint.external_account_id, endpoint.external_chat_namespace)
            print(f"[crm] whatsapp endpoint sync response endpoint_id={endpoint.id} result={sync_result}")

            imported = _to_int(sync_result.get("imported") or sync_result.get("forwarded"))
            total_imported += imported
            results.append({
                "endpoint_id": endpoint.id,
                "tenant_id": endpoint.tenant_id,
                "chat_id": endpoint.external_chat_namespace,
                "imported": imported,
                "fetched": _to_int(sync_result.get("fetched")),
                "deduped": _to_int(sync_result.get("deduped")),
                "failed": _to_int(sync_result.get("failed")),
                "inbound": _to_int(sync_result.get("inbound")),
                "outbound": _to_int(sync_result.get("outbound")),
            })

            # Mirrors the reconciliation step in resync_thread_whatsapp_link: without it,
            # messages imported here won't match the timeline filter until resynced individually.
            if endpoint.external_account_id and endpoint.external_chat_namespace:
                matching_messages = db.query(Communication).filter(
                    Communication.tenant_id == endpoint.tenant_id,
                    Communication.channel == "whatsapp",
                    Communication.external_account_id == endpoint.external_account_id,
                ).all()

                chat_id_lower = endpoint.external_chat_namespace.strip().lower()
                messages_updated = 0
                for msg in matching_messages:
                    msg_identity = (msg.whatsapp_identity_key or msg.whatsapp_chat_id or "").strip().lower()
                    if msg_identity and msg_identity == chat_id_lower:
                        if msg.external_chat_namespace != endpoint.external_chat_namespace:
                            msg.external_chat_namespace = endpoint.external_chat_namespace
                            messages_updated += 1

                if messages_updated > 0:
                    db.commit()
                    print(
                        f"[crm] whatsapp endpoint sync reconciled_messages endpoint_id={endpoint.id} count={messages_updated}"
                    )

            print(
                f"[crm] whatsapp endpoint sync completed endpoint_id={endpoint.id} imported={imported}"
            )
        except Exception as exc:
            logger.exception("WhatsApp endpoint sync failed endpoint_id=%s: %s", endpoint.id, str(exc))
            errors.append({
                "endpoint_id": endpoint.id,
                "tenant_id": endpoint.tenant_id,
                "error": str(exc),
            })

    return {
        "synced_endpoints": len(results),
        "total_imported": total_imported,
        "results": results,
        "errors": errors,
    }


async def _debug_whatsapp_history_sync() -> dict[str, Any]:
    import os

    whatsapp_service_url = os.getenv("WHATSAPP_SERVICE_URL", "").strip()
    whatsapp_api_key = os.getenv("WHATSAPP_API_KEY", "").strip()
    if not whatsapp_service_url or not whatsapp_api_key:
        return {"ready": False, "error": "WhatsApp service URL or API key is not configured"}

    url = whatsapp_service_url.rstrip("/") + "/admin/debug/whatsapp-history-sync"
    payload = {"chatCount": 3, "limit": 50}
    print(f"[crm] whatsapp debug request method=POST url={url} timeout=600.0 payload={payload}")
    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(url, headers={"X-API-Key": whatsapp_api_key}, json=payload)
        print(f"[crm] whatsapp debug response status={response.status_code} url={url}")
        response.raise_for_status()
        return response.json()


class SyncAllRequest(BaseModel):
    # Tenant ids currently visible in the requesting user's filtered tenant list. When
    # omitted/empty, sync-all falls back to its historical unscoped, all-tenants behavior.
    tenant_ids: list[int] | None = None


SYNC_ALL_JOB_KIND = "admin_sync_all"
# Generous: a real full run is ~2 minutes, dominated by Gmail. This is a backstop against a
# wedged connection, not a performance budget.
EMAIL_PHASE_TIMEOUT_SECONDS = 900

_SYNC_ALL_PHASES = ("beds24", "email", "whatsapp", "threads")


def _record_partial_failure(summary: dict[str, Any], step: str, error: str) -> None:
    summary["partial_failures"].append({"step": step, "error": error})


def _rebuild_tenant_thread_timeline(tenant_id: int) -> None:
    """Build one tenant's timeline in an isolated session.

    sync-all only needs the rebuild side effects to finish and report progress. Giving each
    tenant its own session keeps a per-tenant timeout safe: if one tenant wedges, the rest of
    the loop can keep moving without sharing a half-blocked Session object across threads.
    """
    db = SessionLocal()
    try:
        build_tenant_thread_timeline(db, tenant_id)
    finally:
        db.close()


def _sync_gmail_account_in_fresh_session(account_id: int, tenant_ids: list[int] | None = None) -> int:
    """Sync one Gmail account using a session owned entirely by the worker thread.

    _sync_gmail_account commits several times and can run for a while. Keeping its Session
    local to the thread avoids sharing the request/job coroutine's Session across a
    cancellable threadpool boundary, which is what led to close()/commit() conflicts when a
    timeout or cancellation landed mid-flight.
    """
    db = SessionLocal()
    try:
        account = db.query(GmailAccount).filter(GmailAccount.id == account_id).first()
        if account is None:
            return 0
        return _sync_gmail_account(db, account, tenant_ids)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _run_sync_all(job_id: str, user_id: int | None, tenant_ids: list[int] | None) -> dict[str, Any]:
    """Job body for sync-all. See sync_all() for why this can't run inside the request.

    Owns its own Session: the request-scoped session from get_db is closed as soon as the 202
    is returned, so reusing it here would fail on the first query. Mirrors the session handling
    in app.main's background Gmail pollers.
    """
    summary: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
        "bookings_updated": 0,
        "emails_imported": 0,
        "whatsapp_messages_imported": 0,
        "whatsapp_endpoints_synced": 0,
        "whatsapp_endpoint_sync_details": [],
        "tenant_threads_updated": 0,
        "partial_failures": [],
    }

    def _phase(name: str, current: int = 0, total: int = 0) -> None:
        update_job_progress(
            job_id,
            phase=name,
            phase_index=_SYNC_ALL_PHASES.index(name) + 1,
            phases_total=len(_SYNC_ALL_PHASES),
            current=current,
            total=total,
        )

    db = SessionLocal()
    try:
        _phase("beds24")
        try:
            summary["bookings_updated"] = await asyncio.wait_for(
                _sync_beds24(db, user_id, tenant_ids),
                timeout=EMAIL_PHASE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            db.rollback()
            logger.warning("sync-all beds24 phase timed out after %ss job_id=%s", EMAIL_PHASE_TIMEOUT_SECONDS, job_id)
            _record_partial_failure(summary, "beds24", f"Timed out after {EMAIL_PHASE_TIMEOUT_SECONDS}s")
        except Exception as exc:
            db.rollback()
            logger.exception("sync-all beds24 phase failed job_id=%s", job_id)
            _record_partial_failure(summary, "beds24", str(exc))

        _phase("email")
        try:
            # Bounded so a Gmail call that stalls past its own socket timeout can still never
            # strand the whole job in "running" - the remaining phases run and the job reaches
            # a terminal state, with the timeout recorded as a partial failure.
            summary["emails_imported"] = await asyncio.wait_for(
                _sync_emails(db, tenant_ids, progress=lambda current, total: _phase("email", current, total)),
                timeout=EMAIL_PHASE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            db.rollback()
            logger.warning("sync-all email phase timed out after %ss job_id=%s", EMAIL_PHASE_TIMEOUT_SECONDS, job_id)
            _record_partial_failure(summary, "email", f"Timed out after {EMAIL_PHASE_TIMEOUT_SECONDS}s")
        except Exception as exc:
            db.rollback()
            logger.exception("sync-all email phase failed job_id=%s", job_id)
            _record_partial_failure(summary, "email", str(exc))

        _phase("whatsapp")
        try:
            whatsapp_result = await asyncio.wait_for(
                _sync_whatsapp_linked_endpoints(db, tenant_ids),
                timeout=EMAIL_PHASE_TIMEOUT_SECONDS,
            )
            summary["whatsapp_messages_imported"] = whatsapp_result.get("total_imported", 0)
            summary["whatsapp_endpoints_synced"] = whatsapp_result.get("synced_endpoints", 0)
            summary["whatsapp_endpoint_sync_details"] = whatsapp_result.get("results", [])
            if whatsapp_result.get("errors"):
                summary["partial_failures"].append({
                    "step": "whatsapp_endpoints",
                    "errors": whatsapp_result.get("errors", []),
                })
        except asyncio.TimeoutError:
            db.rollback()
            logger.warning("sync-all whatsapp phase timed out after %ss job_id=%s", EMAIL_PHASE_TIMEOUT_SECONDS, job_id)
            _record_partial_failure(summary, "whatsapp", f"Timed out after {EMAIL_PHASE_TIMEOUT_SECONDS}s")
        except Exception as exc:
            db.rollback()
            logger.exception("sync-all whatsapp phase failed job_id=%s", job_id)
            _record_partial_failure(summary, "whatsapp", str(exc))

        try:
            summary["tenant_threads_updated"] = 0
            thread_tenant_query = db.query(Tenant)
            if tenant_ids is not None:
                thread_tenant_query = thread_tenant_query.filter(Tenant.id.in_(tenant_ids))
            tenants = thread_tenant_query.order_by(Tenant.id.asc()).all()
            _phase("threads", current=0, total=len(tenants))
            for tenant in tenants:
                # Rebuilding every tenant's thread timeline synchronously in this loop, with no
                # yield points, would freeze this worker's event loop (and every other concurrent
                # request — logins, thread loads, everything) for the whole loop's duration.
                try:
                    await asyncio.wait_for(
                        run_in_threadpool(_rebuild_tenant_thread_timeline, tenant.id),
                        timeout=EMAIL_PHASE_TIMEOUT_SECONDS,
                    )
                    summary["tenant_threads_updated"] += 1
                except asyncio.TimeoutError:
                    logger.warning(
                        "sync-all tenant_threads tenant timed out after %ss job_id=%s tenant_id=%s",
                        EMAIL_PHASE_TIMEOUT_SECONDS,
                        job_id,
                        tenant.id,
                    )
                    _record_partial_failure(
                        summary,
                        "tenant_threads",
                        f"Tenant {tenant.id} timed out after {EMAIL_PHASE_TIMEOUT_SECONDS}s",
                    )
                _phase("threads", current=summary["tenant_threads_updated"], total=len(tenants))
        except Exception as exc:
            db.rollback()
            logger.exception("sync-all tenant_threads phase failed job_id=%s", job_id)
            _record_partial_failure(summary, "tenant_threads", str(exc))
    finally:
        db.close()

    summary["completed_at"] = datetime.now(timezone.utc)
    return summary


@router.post("/sync-all", status_code=status.HTTP_202_ACCEPTED)
async def sync_all(
    payload: SyncAllRequest | None = None,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Start a sync-all run in the background and return a job id to poll.

    This used to await all four phases inline and return the summary. A full run takes ~2
    minutes (the Gmail phase alone dominates), so nginx's proxy_read_timeout closed the
    connection and the caller got a 504 even though the sync itself completed. Returning
    immediately decouples the response from however long the work takes.
    """
    tenant_ids = payload.tenant_ids if payload else None

    # Single-flight: a double-click used to start a second concurrent run, doubling the load
    # on the Gmail and WhatsApp upstreams for no benefit.
    running_job_id = find_running_job(SYNC_ALL_JOB_KIND)
    if running_job_id is not None:
        return {"job_id": running_job_id, "status": "running", "already_running": True}

    # The id is generated up front so the runner can report progress against the same id the
    # caller is about to poll.
    job_id = uuid.uuid4().hex
    start_job(
        SYNC_ALL_JOB_KIND,
        _run_sync_all(job_id, getattr(current_user, "id", None), tenant_ids),
        job_id=job_id,
    )
    return {"job_id": job_id, "status": "running", "already_running": False}


@router.post("/sync-all/{job_id}/cancel")
async def cancel_sync_all(job_id: str, current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    """Stop reporting a wedged sync-all as in-flight so a new run can be started.

    The underlying Gmail work may still be winding down in its worker thread; this releases
    the single-flight guard and the client's blocking progress overlay.
    """
    if get_job(job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync job not found")
    cancelled = cancel_job(job_id)
    logger.info("sync-all cancel requested job_id=%s cancelled=%s user_id=%s", job_id, cancelled, getattr(current_user, "id", None))
    return {"job_id": job_id, "cancelled": cancelled}


@router.get("/sync-all/{job_id}")
async def sync_all_status(job_id: str, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync job not found")
    return job


@router.post("/debug/whatsapp-history-sync")
async def debug_whatsapp_history_sync(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    return await _debug_whatsapp_history_sync()
