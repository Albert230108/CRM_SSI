from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.api.tenants import ROOM_ID_MAPPING, _extract_guest_fields
from app.models.finance import Finance
from app.models.tenant import Tenant
from app.services.beds24_service import fetch_booking_with_invoice
from app.services.tenant_phone_aliases import sync_tenant_phone_aliases

logger = logging.getLogger(__name__)


async def sync_tenant_from_beds24_booking(
    db: Session,
    booking_id: str,
    booking: dict[str, Any] | None = None,
    allow_create: bool = True,
) -> Tenant | None:
    """
    Upsert the Tenant row and rewrite its Finance rows from a Beds24 booking
    payload. Used by the Quotation Manager's "send to Beds24" endpoint
    (app.api.quotation) to refresh Finance immediately after pushing invoice
    item changes to Beds24, using the same upsert shape the live Beds24
    webhook (app.api.beds24_webhooks._process_beds24_booking_event) applies -
    that webhook handler is left untouched here since it also owns
    webhook-delivery logging/deduplication concerns this helper doesn't need.

    Args:
        booking: an already-fetched booking payload, to avoid a redundant
            Beds24 call when the caller fetched it moments earlier. If None,
            this fetches it itself.
        allow_create: if False, an unknown booking_id with no existing Tenant
            row is left uncreated (used by the webhook to skip creating a
            tenant purely to record a cancellation of a booking never seen
            before).

    Returns:
        The synced Tenant, or None if Beds24 returned no booking data, or if
        the tenant doesn't exist and allow_create is False.
    """
    if booking is None:
        booking = await fetch_booking_with_invoice(booking_id)
    if not booking:
        logger.warning("Beds24 returned empty booking for booking_id=%s", booking_id)
        return None

    fields = _extract_guest_fields(booking)
    room_name = str(booking.get("roomName") or booking.get("unitName") or "").strip() or None
    room_id = ROOM_ID_MAPPING.get(room_name) if room_name else fields.get("room_id")

    tenant = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
    if tenant is None:
        if not allow_create:
            return None
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
    sync_tenant_phone_aliases(db, tenant, primary_phone=tenant.phone, alias_phones=[tenant.mobile])

    db.flush()

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

    logger.info("Tenant synced from Beds24: tenant_id=%s booking_id=%s", tenant.id, booking_id)
    return tenant
