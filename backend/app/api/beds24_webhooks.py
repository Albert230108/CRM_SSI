from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.gmail_integration import sync_email_across_gmail_accounts
from app.api.tenants import ROOM_ID_MAPPING, _extract_guest_fields
from app.core.dependencies import get_current_admin_user, get_db
from app.models.beds24_webhook_log import Beds24WebhookLog
from app.models.finance import Finance
from app.models.tenant import Tenant
from app.schemas.beds24_webhook_log import Beds24WebhookLogRead
from app.services.background_jobs import start_job
from app.services.beds24_client import get_booking_info_items
from app.services.beds24_service import fetch_booking_with_invoice
from app.services.tenant_ai_template_provisioning import (
    apply_default_brain_action_writer_settings,
    apply_default_formatter_settings,
    apply_default_planner_mode,
)
from app.services.tenant_email_sync import sync_tenant_email_addresses_from_beds24
from app.services.tenant_notes_history import SOURCE_BEDS24_WEBHOOK, set_tenant_notes
from app.services.tenant_phone_aliases import sync_tenant_phone_aliases

router = APIRouter(prefix="/webhooks/beds24", tags=["beds24-webhooks"])
logger = logging.getLogger(__name__)


def _extract_booking_id(payload: dict[str, Any]) -> str | None:
    booking = payload.get("booking")
    nested = booking if isinstance(booking, dict) else {}
    value = (
        payload.get("bookingId")
        or payload.get("booking_id")
        or payload.get("id")
        or nested.get("id")
        or nested.get("bookingId")
    )
    return str(value).strip() if value is not None and str(value).strip() else None


def _extract_external_event_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("eventId") or payload.get("event_id") or payload.get("webhookId") or payload.get("webhook_id")
    return str(value).strip() if value is not None and str(value).strip() else None


def _is_authorized(request: Request, payload: dict[str, Any]) -> bool:
    expected_secret = os.getenv("BEDS24_WEBHOOK_SECRET", "")
    if not expected_secret:
        return True
    query_secret = request.query_params.get("secret")
    header_secret = request.headers.get("X-Beds24-Secret")
    body_secret = payload.get("secret")
    return expected_secret in {query_secret, header_secret, body_secret}


def _dedupe_key(event_type: str | None, booking_id: str | None, external_event_id: str | None, payload: dict[str, Any]) -> str:
    if external_event_id:
        return f"event:{external_event_id}"
    digest = hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()
    return f"booking:{booking_id or 'unknown'}:event:{event_type or 'unknown'}:hash:{digest}"


def _summarize_payload(payload: dict[str, Any], booking_id: str | None, event_type: str | None, room_id: Any, tenant_id: Any) -> dict[str, Any]:
    return {
        "booking_id": booking_id,
        "event_type": event_type,
        "room_id": str(room_id) if room_id is not None else None,
        "tenant_id": tenant_id,
        "keys": sorted(list(payload.keys()))[:25],
    }


@router.get("/admin/logs", response_model=list[Beds24WebhookLogRead], dependencies=[Depends(get_current_admin_user)])
def list_beds24_webhook_logs(
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    event_type: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Beds24WebhookLog]:
    query = db.query(Beds24WebhookLog)
    if status_filter:
        query = query.filter(Beds24WebhookLog.status == status_filter.strip().lower())
    if event_type:
        query = query.filter(Beds24WebhookLog.event_type == event_type.strip().lower())
    if start is not None:
        query = query.filter(Beds24WebhookLog.received_at >= start)
    if end is not None:
        query = query.filter(Beds24WebhookLog.received_at <= end)
    return query.order_by(Beds24WebhookLog.received_at.desc(), Beds24WebhookLog.id.desc()).limit(limit).all()


@router.get("/admin/logs/{log_id}", response_model=Beds24WebhookLogRead, dependencies=[Depends(get_current_admin_user)])
def get_beds24_webhook_log(log_id: int, db: Session = Depends(get_db)) -> Beds24WebhookLog:
    log = db.query(Beds24WebhookLog).filter(Beds24WebhookLog.id == log_id).first()
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")
    return log


async def _process_beds24_booking_event(
    db: Session,
    *,
    booking_id: str | None,
    event: str,
    external_event_id: str | None,
    dedupe_key: str,
    raw_payload: dict[str, Any],
) -> dict[str, str]:
    existing = db.query(Beds24WebhookLog).filter(Beds24WebhookLog.provider == "beds24", Beds24WebhookLog.dedupe_key == dedupe_key).first()
    if existing is not None:
        duplicate = Beds24WebhookLog(
            provider="beds24",
            received_at=datetime.now(timezone.utc),
            processed_at=datetime.now(timezone.utc),
            dedupe_key=dedupe_key,
            external_event_id=external_event_id,
            event_type=event or None,
            status="duplicate",
            booking_id=booking_id,
            raw_payload=raw_payload,
            parsed_fields=_summarize_payload(raw_payload, booking_id, event or None, None, None),
            http_status=200,
            result_message="duplicate delivery ignored",
        )
        db.add(duplicate)
        db.commit()
        return {"status": "ok", "detail": "duplicate delivery ignored"}

    log = Beds24WebhookLog(
        provider="beds24",
        received_at=datetime.now(timezone.utc),
        dedupe_key=dedupe_key,
        external_event_id=external_event_id,
        event_type=event or None,
        status="received",
        booking_id=booking_id,
        raw_payload=raw_payload,
        parsed_fields=_summarize_payload(raw_payload, booking_id, event or None, None, None),
    )
    db.add(log)
    db.flush()

    if not booking_id:
        log.status = "failed"
        log.http_status = 400
        log.error_summary = "Missing booking_id"
        log.processed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing booking_id")

    is_cancellation = any(token in event for token in ("delete", "cancel", "remove"))
    try:
        booking = await fetch_booking_with_invoice(booking_id)
        if not booking:
            log.status = "ignored"
            log.http_status = 200
            log.result_message = "booking not found in Beds24"
            log.processed_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "ok", "detail": "booking not found in Beds24"}

        fields = _extract_guest_fields(booking)
        room_name = str(booking.get("roomName") or booking.get("unitName") or "").strip() or None
        room_id = ROOM_ID_MAPPING.get(room_name) if room_name else fields.get("room_id")
        tenant = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
        if tenant is None:
            if is_cancellation:
                log.status = "ignored"
                log.http_status = 200
                log.result_message = "cancellation for unknown booking, skipped"
                log.processed_at = datetime.now(timezone.utc)
                db.commit()
                return {"status": "ok", "detail": "cancellation for unknown booking, skipped"}
            tenant = Tenant(booking_id=booking_id, name=fields.get("name") or booking_id)
            db.add(tenant)
            db.flush()
            apply_default_planner_mode(db, tenant.id)
            apply_default_brain_action_writer_settings(db, tenant.id)
            apply_default_formatter_settings(db, tenant.id)

        tenant.name = fields.get("name") or booking_id
        tenant.first_name = fields.get("first_name")
        tenant.last_name = fields.get("last_name")
        # Beds24's main guest email is no longer authoritative: it is whatever address the OTA
        # forwarded, which is frequently an alias that never reaches the guest. The CRM_EMAIL info
        # item, surfaced as a TenantEmailAddress link, is the single source of truth now, so this
        # sync deliberately leaves tenant.email alone.
        tenant.phone = fields.get("phone")
        tenant.mobile = fields.get("mobile")
        tenant.check_in = fields.get("check_in")
        tenant.check_out = fields.get("check_out")
        tenant.booking_status = fields.get("booking_status")
        set_tenant_notes(db, tenant, fields.get("notes"), source=SOURCE_BEDS24_WEBHOOK)
        tenant.responsible_comm = fields.get("responsible_comm")
        tenant.room_id = room_id
        if hasattr(tenant, "room_name"):
            tenant.room_name = fields.get("room_name")
        if hasattr(tenant, "city"):
            tenant.city = fields.get("city")
        if hasattr(tenant, "country"):
            tenant.country = fields.get("country")
        if hasattr(tenant, "zip_code"):
            tenant.zip_code = fields.get("zip_code")
        if hasattr(tenant, "address"):
            tenant.address = fields.get("address")
        if hasattr(tenant, "company"):
            tenant.company = fields.get("company")
        if hasattr(tenant, "language"):
            tenant.language = fields.get("language")
        if hasattr(tenant, "num_adults"):
            tenant.num_adults = fields.get("num_adults")
        if hasattr(tenant, "num_children"):
            tenant.num_children = fields.get("num_children")
        if hasattr(tenant, "num_nights"):
            tenant.num_nights = fields.get("num_nights")
        if hasattr(tenant, "arrival_time"):
            tenant.arrival_time = fields.get("arrival_time")
        if hasattr(tenant, "departure_time"):
            tenant.departure_time = fields.get("departure_time")
        if hasattr(tenant, "source"):
            tenant.source = fields.get("source")
        if hasattr(tenant, "referer"):
            tenant.referer = fields.get("referer")
        if hasattr(tenant, "total_price"):
            tenant.total_price = fields.get("total_price")
        if hasattr(tenant, "commission"):
            tenant.commission = fields.get("commission")
        if hasattr(tenant, "deposit"):
            tenant.deposit = fields.get("deposit")
        if hasattr(tenant, "currency"):
            tenant.currency = fields.get("currency")
        if hasattr(tenant, "beds24_raw"):
            tenant.beds24_raw = booking
        sync_tenant_phone_aliases(db, tenant, primary_phone=tenant.phone, alias_phones=[tenant.mobile])
        db.flush()
        log.tenant_id = tenant.id
        log.room_id = str(room_id) if room_id is not None else None
        log.parsed_fields = _summarize_payload(raw_payload, booking_id, event or None, room_id, tenant.id)

        invoice_items = booking.get("invoiceItems") or []
        if invoice_items:
            db.query(Finance).filter(Finance.tenant_id == tenant.id).delete(synchronize_session=False)
            for item in invoice_items:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "").lower()
                if item_type not in ("charge", "payment"):
                    continue
                qty = item.get("qty", 1) or 1
                amount = item.get("amount", 0) or 0
                line_total = Decimal(str(amount)) * Decimal(str(qty))
                description = str(item.get("description") or item.get("type") or "").strip()
                db.add(
                    Finance(
                        tenant_id=tenant.id,
                        type=item_type,
                        amount=line_total,
                        currency=str(item.get("currency") or "EUR"),
                        description=description,
                    )
                )

        newly_linked_emails: list[str] = []
        try:
            info_items = await get_booking_info_items(booking_id)
            newly_linked_emails = sync_tenant_email_addresses_from_beds24(db, tenant, info_items)
        except Exception:
            # Info-item sync is best-effort: a Beds24 read hiccup here must not abort the
            # tenant/finance upsert this webhook is otherwise committing below.
            logger.warning(
                "Beds24 webhook info item sync failed booking_id=%s tenant_id=%s", booking_id, tenant.id, exc_info=True
            )

        db.commit()
        log.status = "processed"
        log.http_status = 200
        log.result_message = "tenant upserted"
        log.processed_at = datetime.now(timezone.utc)
        db.commit()

        # Search Gmail history for any address the CRM_EMAIL reconciliation above just linked,
        # so past messages surface in this tenant's thread instead of only future ones. Fired
        # after both commits so the background job's own DB session can see the new link.
        for email in newly_linked_emails:
            start_job("gmail_sync_email", asyncio.to_thread(sync_email_across_gmail_accounts, email))

        return {"status": "ok", "booking_id": booking_id}
    except Exception as exc:
        db.rollback()
        log.status = "failed"
        log.http_status = 500
        log.error_summary = str(exc).strip()[:500]
        log.error_traceback = traceback.format_exc()
        log.processed_at = datetime.now(timezone.utc)
        db.add(log)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        raise


@router.post("")
async def beds24_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")
    if not _is_authorized(request, payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    booking_id = _extract_booking_id(payload)
    external_event_id = _extract_external_event_id(payload)
    event = str(payload.get("event") or payload.get("type") or payload.get("action") or "").lower()
    dedupe_key = _dedupe_key(event or None, booking_id, external_event_id, payload)

    return await _process_beds24_booking_event(
        db,
        booking_id=booking_id,
        event=event,
        external_event_id=external_event_id,
        dedupe_key=dedupe_key,
        raw_payload=payload,
    )


@router.get("")
async def beds24_booking_notifier(
    request: Request,
    db: Session = Depends(get_db),
    bookid: str | None = Query(default=None),
    booking_status: str | None = Query(default=None, alias="status"),
) -> dict[str, str]:
    payload = {"bookid": bookid, "status": booking_status}
    if not _is_authorized(request, payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    booking_id = str(bookid).strip() if bookid is not None and str(bookid).strip() else None
    event = (booking_status or "").lower()
    # No event id/timestamp in this payload shape, so a content hash would dedupe
    # distinct real updates that share the same bookid/status; always process instead.
    dedupe_key = f"notifier:{booking_id or 'unknown'}:{uuid.uuid4()}"

    return await _process_beds24_booking_event(
        db,
        booking_id=booking_id,
        event=event,
        external_event_id=None,
        dedupe_key=dedupe_key,
        raw_payload=payload,
    )
