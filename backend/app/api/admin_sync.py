from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.gmail_integration import _sync_gmail_account
from app.api.tenants import _extract_guest_fields
from app.core.dependencies import get_current_admin_user, get_current_user, get_db
from app.models.gmail_integration import GmailAccount
from app.models.tenant import Tenant
from app.models.user import User
from app.services.beds24_client import get_bookings, get_booking_detail
from app.services.tenant_phone_aliases import sync_tenant_phone_aliases
from app.services.thread_timeline_service import build_tenant_thread_timeline

router = APIRouter(prefix="/admin", tags=["admin-sync"])
logger = logging.getLogger(__name__)
_whatsapp_sync_tasks: set[asyncio.Task[Any]] = set()


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _update_tenant_from_beds24(db: Session, tenant: Tenant, booking: dict[str, Any]) -> None:
    fields = _extract_guest_fields(booking)
    tenant.first_name = fields.get("first_name")
    tenant.last_name = fields.get("last_name")
    tenant.email = fields.get("email")
    tenant.phone = fields.get("phone")
    tenant.mobile = fields.get("mobile")
    tenant.check_in = fields.get("check_in")
    tenant.check_out = fields.get("check_out")
    tenant.city = fields.get("city")
    tenant.country = fields.get("country")
    tenant.zip_code = fields.get("zip_code")
    tenant.address = fields.get("address")
    tenant.company = fields.get("company")
    tenant.language = fields.get("language")
    tenant.num_adults = fields.get("num_adults")
    tenant.num_children = fields.get("num_children")
    tenant.num_nights = fields.get("num_nights")
    tenant.arrival_time = fields.get("arrival_time")
    tenant.departure_time = fields.get("departure_time")
    tenant.room_name = fields.get("room_name")
    tenant.source = fields.get("source")
    tenant.referer = fields.get("referer")
    tenant.total_price = fields.get("total_price")
    tenant.commission = fields.get("commission")
    tenant.deposit = fields.get("deposit")
    tenant.currency = fields.get("currency")
    tenant.notes = fields.get("notes")
    tenant.booking_status = fields.get("booking_status")
    tenant.responsible_comm = fields.get("responsible_comm")
    tenant.name = fields.get("name") or tenant.name
    tenant.beds24_raw = booking
    room_id = fields.get("room_id")
    tenant.room_id = room_id if room_id is not None else tenant.room_id
    sync_tenant_phone_aliases(db, tenant, primary_phone=tenant.phone, alias_phones=[tenant.mobile])


async def _sync_beds24(db: Session, current_user: User) -> int:
    updated = 0
    bookings = await get_bookings()
    for booking in bookings:
        booking_id = str(booking.get("id") or "").strip()
        if not booking_id:
            continue

        tenant = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
        if tenant is None:
            continue

        try:
            booking_detail = await get_booking_detail(booking_id)
        except Exception:
            booking_detail = booking

        _update_tenant_from_beds24(db, tenant, booking_detail if isinstance(booking_detail, dict) else booking)
        updated += 1
    db.commit()
    return updated


async def _sync_emails(db: Session, current_user: User) -> int:
    accounts = db.query(GmailAccount).filter(GmailAccount.is_active.is_(True)).order_by(GmailAccount.id.asc()).all()
    imported = 0
    for account in accounts:
        # _sync_gmail_account makes blocking, synchronous Gmail API calls (up to 100 threads
        # per account) with no yield points of its own. Looping it inline here would monopolize
        # this worker's event loop for every other concurrent request until all accounts finished.
        imported += await run_in_threadpool(_sync_gmail_account, db, account)
    return imported


async def _sync_whatsapp_linked_endpoints(db: Session) -> dict[str, Any]:
    """Sync WhatsApp history for all manually linked endpoints.

    For each tenant with active manual WhatsApp links:
    - Trigger full history resync via the WhatsApp service
    - Aggregate results per endpoint
    """
    import os

    from app.models.tenant_channel_endpoint import TenantChannelEndpoint

    whatsapp_service_url = os.getenv("WHATSAPP_SERVICE_URL", "").strip()
    whatsapp_api_key = os.getenv("WHATSAPP_API_KEY", "").strip()
    if not whatsapp_service_url or not whatsapp_api_key:
        return {
            "synced_endpoints": 0,
            "total_imported": 0,
            "results": [],
            "errors": [],
        }

    # Find all active WhatsApp endpoints with manual links (external_chat_namespace set)
    active_links = (
        db.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.is_active.is_(True),
            TenantChannelEndpoint.external_chat_namespace.isnot(None),
        )
        .all()
    )

    results = []
    errors = []
    total_imported = 0

    for endpoint in active_links:
        try:
            url = whatsapp_service_url.rstrip("/") + "/admin/backfill"
            payload = {
                "limit": 100000,
                "chatId": endpoint.external_chat_namespace,
                "postSyncDelayMs": 0,
            }
            print(
                f"[crm] whatsapp endpoint sync request endpoint_id={endpoint.id} chat_id={endpoint.external_chat_namespace} method=POST url={url}"
            )
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(url, headers={"X-API-Key": whatsapp_api_key}, json=payload)
                print(f"[crm] whatsapp endpoint sync response status={response.status_code} endpoint_id={endpoint.id}")
                response.raise_for_status()
                sync_result = response.json()

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


async def _sync_whatsapp() -> int:
    """Legacy: Full account-level sync (kept for compatibility).

    New behavior: Delegates to per-endpoint sync for manually linked chats.
    """
    # This is now handled by _sync_whatsapp_linked_endpoints in main sync
    return 0




def _queue_whatsapp_sync() -> None:
    task = asyncio.create_task(_sync_whatsapp())
    _whatsapp_sync_tasks.add(task)

    def _log_completion(completed: asyncio.Task[Any]) -> None:
        _whatsapp_sync_tasks.discard(completed)
        try:
            imported = completed.result()
            logger.info("Queued WhatsApp sync finished imported=%s", imported)
        except Exception:
            logger.exception("Queued WhatsApp sync failed")

    task.add_done_callback(_log_completion)


@router.get("/sync-status")
async def sync_status(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    running_tasks = [task for task in _whatsapp_sync_tasks if not task.done()]
    return {
        "whatsapp_sync_running": bool(running_tasks),
        "whatsapp_sync_task_count": len(running_tasks),
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


@router.post("/sync-all")
async def sync_all(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, Any]:
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

    try:
        summary["bookings_updated"] = await _sync_beds24(db, current_user)
    except Exception as exc:
        summary["partial_failures"].append({"step": "beds24", "error": str(exc)})

    try:
        summary["emails_imported"] = await _sync_emails(db, current_user)
    except Exception as exc:
        summary["partial_failures"].append({"step": "email", "error": str(exc)})

    try:
        whatsapp_result = await _sync_whatsapp_linked_endpoints(db)
        summary["whatsapp_messages_imported"] = whatsapp_result.get("total_imported", 0)
        summary["whatsapp_endpoints_synced"] = whatsapp_result.get("synced_endpoints", 0)
        summary["whatsapp_endpoint_sync_details"] = whatsapp_result.get("results", [])
        if whatsapp_result.get("errors"):
            summary["partial_failures"].append({
                "step": "whatsapp_endpoints",
                "errors": whatsapp_result.get("errors", []),
            })
    except Exception as exc:
        summary["partial_failures"].append({"step": "whatsapp", "error": str(exc)})

    try:
        summary["tenant_threads_updated"] = 0
        for tenant in db.query(Tenant).order_by(Tenant.id.asc()).all():
            # Rebuilding every tenant's thread timeline synchronously in this loop, with no
            # yield points, would freeze this worker's event loop (and every other concurrent
            # request — logins, thread loads, everything) for the whole loop's duration.
            await run_in_threadpool(build_tenant_thread_timeline, db, tenant.id)
            summary["tenant_threads_updated"] += 1
    except Exception as exc:
        summary["partial_failures"].append({"step": "tenant_threads", "error": str(exc)})

    summary["completed_at"] = datetime.now(timezone.utc)
    return summary


@router.post("/debug/whatsapp-history-sync")
async def debug_whatsapp_history_sync(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    return await _debug_whatsapp_history_sync()
