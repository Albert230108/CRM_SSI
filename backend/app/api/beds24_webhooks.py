from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.tenants import ROOM_ID_MAPPING, _extract_guest_fields
from app.core.dependencies import get_current_admin_user, get_db
from app.models.beds24_webhook_log import Beds24WebhookLog
from app.models.finance import Finance
from app.models.tenant import Tenant
from app.schemas.beds24_webhook_log import Beds24WebhookLogRead
from app.services.beds24_service import fetch_booking_with_invoice

router = APIRouter(prefix="/webhooks/beds24", tags=["beds24-webhooks"])


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


def _is_authorized(request: Request, payload: dict[str, Any]) -> bool:
    expected_secret = os.getenv("BEDS24_WEBHOOK_SECRET", "")
    if not expected_secret:
        return True
    query_secret = request.query_params.get("secret")
    header_secret = request.headers.get("X-Beds24-Secret")
    body_secret = payload.get("secret")
    return expected_secret in {query_secret, header_secret, body_secret}


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


@router.post("")
async def beds24_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")
    if not _is_authorized(request, payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    booking_id = _extract_booking_id(payload)
    event = str(payload.get("event") or payload.get("type") or payload.get("action") or "").lower()
    log = Beds24WebhookLog(
        received_at=datetime.now(timezone.utc),
        event_type=event or None,
        status="received",
        booking_id=booking_id,
        raw_payload=payload,
        parsed_fields={},
    )
    db.add(log)
    db.flush()

    if not booking_id:
        log.status = "failed"
        log.http_status = 400
        log.error_summary = "Missing booking_id"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing booking_id")

    is_cancellation = any(token in event for token in ("delete", "cancel", "remove"))
    try:
        booking = await fetch_booking_with_invoice(booking_id)
        if not booking:
            log.status = "ignored"
            log.http_status = 200
            log.result_message = "booking not found in Beds24"
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
                db.commit()
                return {"status": "ok", "detail": "cancellation for unknown booking, skipped"}
            tenant = Tenant(booking_id=booking_id, name=fields.get("name") or booking_id)
            db.add(tenant)
            db.flush()

        tenant.name = fields.get("name") or booking_id
        tenant.first_name = fields.get("first_name")
        tenant.last_name = fields.get("last_name")
        tenant.email = fields.get("email")
        tenant.phone = fields.get("phone")
        tenant.mobile = fields.get("mobile")
        tenant.check_in = fields.get("check_in")
        tenant.check_out = fields.get("check_out")
        tenant.booking_status = fields.get("booking_status")
        tenant.notes = fields.get("notes")
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
        db.flush()
        log.tenant_id = tenant.id
        log.room_id = str(room_id) if room_id is not None else None
        log.parsed_fields = fields

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

        db.commit()
        log.status = "processed"
        log.http_status = 200
        log.result_message = "tenant upserted"
        db.commit()
        return {"status": "ok", "booking_id": booking_id}
    except Exception as exc:
        db.rollback()
        log.status = "failed"
        log.http_status = 500
        log.error_summary = str(exc).strip()[:500]
        log.error_traceback = traceback.format_exc()
        db.add(log)
        db.commit()
        raise
