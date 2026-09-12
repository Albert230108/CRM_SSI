"""Single source of truth for turning Beds24 invoice items into Finance rows.

Four separate call sites used to inline their own version of this loop (manual import,
live webhook, the quotation/auto-draft sync, and the legacy webhook module), and they had
drifted: two of them never persisted qty/unit_price/vat_rate/status at all, so the Tenant
Info table rendered an em dash in four of its six columns. Keeping the mapping here means
every sync path captures the same breakdown.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models.finance import Finance
from app.models.tenant import Tenant
from app.services.beds24_service import strip_description

logger = logging.getLogger(__name__)

_PLACEHOLDER_TOKENS = (
    ("[ROOMNAME1]", ("roomName", "unitName", "propName")),
    ("[ROOMNAME2]", ("roomName", "unitName", "propName")),
    ("[FIRSTNIGHT]", ("arrival", "arrivalDate", "checkIn")),
    ("[CHECKIN]", ("arrival", "arrivalDate", "checkIn")),
    ("[LEAVINGDAY]", ("departure", "departureDate", "checkOut")),
    ("[CHECKOUT]", ("departure", "departureDate", "checkOut")),
    ("[NUMADULTS]", ("numAdult", "adults")),
    ("[NUMCHILDREN]", ("numChild", "children")),
)


def _first_value(booking: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = booking.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def resolve_placeholders(text: str, booking: dict[str, Any]) -> str:
    """Replace Beds24 template tokens in a line description with booking values."""
    text = str(text or "")
    for token, keys in _PLACEHOLDER_TOKENS:
        if token not in text:
            continue
        value = _first_value(booking, keys)
        if value:
            text = text.replace(token, value)
    booking_id = booking.get("id")
    if booking_id not in (None, "") and "[BOOKINGID]" in text:
        text = text.replace("[BOOKINGID]", str(booking_id))
    return text


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError, ArithmeticError):
        return Decimal(default)


def _money(value: Decimal) -> Decimal:
    """Round to the 2dp the finances columns hold.

    Beds24 sends amounts as JSON floats, so both its own lineTotal and any amount*qty
    product can arrive with binary-float noise (e.g. -5025.120000000001). Quantizing here
    keeps the stored value identical across Postgres and the SQLite test DB.
    """
    try:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ArithmeticError):
        return value


def build_finance_rows(tenant_id: int, booking: dict[str, Any]) -> list[Finance]:
    """Map booking["invoiceItems"] to unsaved Finance rows for `tenant_id`."""
    rows: list[Finance] = []
    for item in booking.get("invoiceItems") or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        if item_type not in ("charge", "payment"):
            continue

        qty = _decimal(item.get("qty"), default="1")
        unit_price = _decimal(item.get("amount"))
        # Beds24 sends lineTotal itself; trusting it avoids a rounding drift between the
        # Total column and the figures the guest sees on the Beds24 invoice.
        line_total = _decimal(item.get("lineTotal")) if item.get("lineTotal") not in (None, "") else unit_price * qty

        description = resolve_placeholders(strip_description(item.get("description")), booking)
        raw_status = str(item.get("status") or "").strip()

        rows.append(
            Finance(
                tenant_id=tenant_id,
                type=item_type,
                amount=_money(line_total),
                qty=qty,
                unit_price=_money(unit_price),
                vat_rate=_decimal(item.get("vatRate")),
                currency=str(item.get("currency") or "EUR"),
                description=description or item_type,
                # Beds24 leaves status empty on every charge; only payments carry
                # "not paid" or a paid-on date. Store NULL rather than an empty string.
                status=raw_status or None,
            )
        )
    return rows


def replace_tenant_finance_from_booking(db: Session, tenant: Tenant, booking: dict[str, Any]) -> int:
    """Rebuild a tenant's finance rows from a Beds24 booking payload.

    No-ops when the payload carries no ``invoiceItems`` key. Callers that fetch bookings
    without requesting invoice items would otherwise delete a breakdown captured earlier
    by a path that did request them, which is how the quotation sync used to wipe rows.
    """
    if not isinstance(booking, dict) or "invoiceItems" not in booking:
        return 0

    rows = build_finance_rows(tenant.id, booking)
    db.query(Finance).filter(Finance.tenant_id == tenant.id).delete(synchronize_session=False)
    for row in rows:
        db.add(row)
    logger.info("Finance rows rebuilt from Beds24: tenant_id=%s rows=%s", tenant.id, len(rows))
    return len(rows)
