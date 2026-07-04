from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.gmail_integration import sync_account
from app.api.tenants import ImportTenantRequest, _extract_guest_fields, _import_tenant
from app.core.dependencies import get_current_admin_user, get_db
from app.models.gmail_integration import GmailAccount
from app.models.user import User
from app.services.beds24_client import get_bookings
from app.services.thread_timeline_service import build_tenant_thread_timeline

router = APIRouter(prefix="/admin", tags=["admin-sync"])


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def _sync_beds24(db: Session, current_user: User) -> int:
    updated = 0
    bookings = await get_bookings()
    for booking in bookings:
        booking_id = str(booking.get("id") or "").strip()
        if not booking_id:
            continue
        fields = _extract_guest_fields(booking)
        payload = ImportTenantRequest(
            booking_id=booking_id,
            name=fields.get("name") or booking_id,
            first_name=fields.get("first_name") or "",
            last_name=fields.get("last_name") or "",
            email=fields.get("email"),
            phone=fields.get("phone"),
            mobile=fields.get("mobile"),
            check_in=fields.get("check_in") or "",
            check_out=fields.get("check_out") or "",
            notes=fields.get("notes"),
            booking_status=fields.get("booking_status") or "confirmed",
            responsible_comm=fields.get("responsible_comm"),
        )
        await _import_tenant(data=payload, db=db, current_user=current_user)
        updated += 1
    return updated


async def _sync_emails(db: Session, current_user: User) -> int:
    accounts = db.query(GmailAccount).filter(GmailAccount.is_active.is_(True)).order_by(GmailAccount.id.asc()).all()
    imported = 0
    for account in accounts:
        result = sync_account(account.id, db=db, current_user=current_user)
        imported += _to_int(result.get("synced_threads"))
    return imported


async def _sync_whatsapp() -> int:
    import os

    whatsapp_service_url = os.getenv("WHATSAPP_SERVICE_URL", "").strip()
    whatsapp_api_key = os.getenv("WHATSAPP_API_KEY", "").strip()
    if not whatsapp_service_url or not whatsapp_api_key:
        return 0

    url = whatsapp_service_url.rstrip("/") + "/admin/backfill"
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers={"X-API-Key": whatsapp_api_key}, json={"limit": 200})
        response.raise_for_status()
        payload = response.json()
    return _to_int(payload.get("forwarded"))


@router.post("/sync-all")
async def sync_all(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
        "bookings_updated": 0,
        "emails_imported": 0,
        "whatsapp_messages_imported": 0,
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
        summary["whatsapp_messages_imported"] = await _sync_whatsapp()
    except Exception as exc:
        summary["partial_failures"].append({"step": "whatsapp", "error": str(exc)})

    try:
        tenants = db.query(User).count()
        summary["tenant_threads_updated"] = 0
        from app.models.tenant import Tenant
        for tenant in db.query(Tenant).order_by(Tenant.id.asc()).all():
            build_tenant_thread_timeline(db, tenant.id)
            summary["tenant_threads_updated"] += 1
    except Exception as exc:
        summary["partial_failures"].append({"step": "tenant_threads", "error": str(exc)})

    summary["completed_at"] = datetime.now(timezone.utc)
    return summary
