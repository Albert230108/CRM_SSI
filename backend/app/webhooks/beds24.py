from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.finance import Finance
from app.models.tenant import Tenant
from app.services.beds24_client import get_charges, get_payments

router = APIRouter(prefix="/webhooks/beds24", tags=["beds24-webhooks"])


def _pick_booking_id(payload: dict) -> str | None:
    value = payload.get("booking_id") or payload.get("bookingId") or payload.get("id")
    return str(value) if value is not None and str(value) else None


def _pick_name(payload: dict) -> str:
    name = payload.get("guest_name") or payload.get("guestName") or payload.get("name")
    if name:
        return str(name)
    first_name = str(payload.get("first_name") or payload.get("firstName") or "").strip()
    last_name = str(payload.get("last_name") or payload.get("lastName") or "").strip()
    return " ".join(part for part in [first_name, last_name] if part)


def _amount(item: dict) -> Decimal:
    value = item.get("amount") or item.get("value") or item.get("total") or 0
    return Decimal(str(value))


def _sync_finance(db: Session, tenant_id: int, items: list[dict], description: str) -> None:
    db.query(Finance).filter(Finance.tenant_id == tenant_id).delete()
    for item in items:
        db.add(
            Finance(
                tenant_id=tenant_id,
                amount=_amount(item),
                currency=item.get("currency") or item.get("currencyCode") or "EUR",
                description=item.get("description") or item.get("type") or description,
            )
        )


@router.post("")
async def beds24_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    booking = payload.get("booking") if isinstance(payload.get("booking"), dict) else payload
    booking_id = _pick_booking_id(booking)
    if not booking_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing booking_id")

    tenant = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
    if tenant is None:
        tenant = Tenant(booking_id=booking_id, name=_pick_name(booking) or booking_id)
        db.add(tenant)

    tenant.first_name = booking.get("first_name") or booking.get("firstName")
    tenant.last_name = booking.get("last_name") or booking.get("lastName")
    tenant.email = booking.get("email")
    tenant.phone = booking.get("phone") or booking.get("phone_number")
    tenant.booking_status = booking.get("status") or booking.get("booking_status") or booking.get("state")
    tenant.responsible_comm = booking.get("RESPONSIBLE_COMM") or booking.get("responsible_comm")
    tenant.name = _pick_name(booking) or booking_id

    db.flush()

    payments = payload.get("payments")
    if payments is None:
        payments = await get_payments(booking_id)
    payment_items = payments.get("data") if isinstance(payments, dict) else payments
    if isinstance(payment_items, dict):
        payment_items = payment_items.get("payments") or []

    charges = payload.get("charges")
    if charges is None:
        charges = await get_charges(booking_id)
    charge_items = charges.get("data") if isinstance(charges, dict) else charges
    if isinstance(charge_items, dict):
        charge_items = charge_items.get("charges") or []

    _sync_finance(db, tenant.id, list(payment_items or []), "payment")
    for item in list(charge_items or []):
        db.add(
            Finance(
                tenant_id=tenant.id,
                amount=_amount(item),
                currency=item.get("currency") or item.get("currencyCode") or "EUR",
                description=item.get("description") or item.get("type") or "charge",
            )
        )

    db.commit()
    db.refresh(tenant)
    return {"status": "ok"}
