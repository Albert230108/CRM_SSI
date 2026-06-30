from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.finance import Finance
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantRead
from app.services.beds24_client import get_booking_detail, get_bookings, get_charges, get_payments

router = APIRouter(tags=["tenants"])


def _pick_booking_id(item: dict) -> str | None:
    value = item.get("booking_id") or item.get("id") or item.get("bookingId")
    return str(value) if value is not None and str(value) else None


def _pick_guest_name(item: dict) -> str:
    first_name = item.get("first_name") or item.get("firstName") or ""
    last_name = item.get("last_name") or item.get("lastName") or ""
    name = item.get("guest_name") or item.get("guestName") or item.get("name")
    if name:
        return str(name)
    return " ".join(part for part in [str(first_name).strip(), str(last_name).strip()] if part)


def _normalize_amount(item: dict) -> Decimal:
    value = item.get("amount") or item.get("value") or item.get("total") or 0
    return Decimal(str(value))


@router.get("/tenants", response_model=list[TenantRead])
def list_tenants(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[Tenant]:
    return db.query(Tenant).order_by(Tenant.id).all()


@router.get("/beds24/bookings")
async def beds24_bookings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    bookings = await get_bookings()
    booking_items = bookings.get("data") if isinstance(bookings, dict) else bookings
    if isinstance(booking_items, dict):
        booking_items = booking_items.get("bookings") or []

    results: list[dict] = []
    for item in booking_items or []:
        booking_id = _pick_booking_id(item)
        if not booking_id:
            continue
        tenant = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
        results.append(
            {
                "booking_id": booking_id,
                "guest_name": _pick_guest_name(item),
                "status": item.get("status") or item.get("booking_status") or item.get("state"),
                "imported": tenant is not None,
            }
        )
    return results


@router.post("/tenants/import/{booking_id}", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def import_tenant(booking_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Tenant:
    existing = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Booking already imported")

    booking = await get_booking_detail(booking_id)
    booking_data = booking.get("data") if isinstance(booking, dict) else booking
    if isinstance(booking_data, list):
        booking_data = booking_data[0] if booking_data else {}
    booking_data = booking_data or {}

    first_name = booking_data.get("first_name") or booking_data.get("firstName")
    last_name = booking_data.get("last_name") or booking_data.get("lastName")
    email = booking_data.get("email")
    phone = booking_data.get("phone") or booking_data.get("phone_number")
    booking_status = booking_data.get("status") or booking_data.get("booking_status") or booking_data.get("state")
    responsible_comm = booking_data.get("RESPONSIBLE_COMM") or booking_data.get("responsible_comm")
    name = booking_data.get("guest_name") or booking_data.get("guestName") or " ".join(
        part for part in [str(first_name or "").strip(), str(last_name or "").strip()] if part
    )

    tenant = Tenant(
        booking_id=booking_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        booking_status=booking_status,
        responsible_comm=responsible_comm,
        name=name or booking_id,
    )
    db.add(tenant)
    db.flush()

    payments = await get_payments(booking_id)
    payment_items = payments.get("data") if isinstance(payments, dict) else payments
    if isinstance(payment_items, dict):
        payment_items = payment_items.get("payments") or []
    for item in payment_items or []:
        db.add(
            Finance(
                tenant_id=tenant.id,
                amount=_normalize_amount(item),
                currency=item.get("currency") or item.get("currencyCode") or "EUR",
                description=item.get("description") or item.get("type") or "payment",
            )
        )

    charges = await get_charges(booking_id)
    charge_items = charges.get("data") if isinstance(charges, dict) else charges
    if isinstance(charge_items, dict):
        charge_items = charge_items.get("charges") or []
    for item in charge_items or []:
        db.add(
            Finance(
                tenant_id=tenant.id,
                amount=_normalize_amount(item),
                currency=item.get("currency") or item.get("currencyCode") or "EUR",
                description=item.get("description") or item.get("type") or "charge",
            )
        )

    db.commit()
    db.refresh(tenant)
    return tenant
