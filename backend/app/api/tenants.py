from decimal import Decimal
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.finance import Finance
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantCreate, TenantRead
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


async def _get_graph_access_token() -> str:
    tenant_id = os.getenv("MS_GRAPH_TENANT_ID")
    client_id = os.getenv("MS_GRAPH_CLIENT_ID")
    client_secret = os.getenv("MS_GRAPH_CLIENT_SECRET")
    if not tenant_id or not client_id or not client_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Microsoft Graph is not configured")

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
                "scope": "https://graph.microsoft.com/.default",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to authenticate with Microsoft Graph")
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Microsoft Graph access token missing")
    return str(token)


def _build_one_drive_folder_path(tenant: Tenant) -> str:
    if not tenant.booking_id or not tenant.first_name or not tenant.last_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant booking details are incomplete")
    folder_name = f"{tenant.booking_id}_{tenant.first_name}_{tenant.last_name}".replace(" ", "_")
    return f"/01. Rentals/02. Short-Stay Inn/Tenants/2026/{folder_name}"


@router.get("/tenants", response_model=list[TenantRead])
def list_tenants(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[Tenant]:
    return db.query(Tenant).order_by(Tenant.id).all()


@router.post("/tenants", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(payload: TenantCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Tenant:
    existing = db.query(Tenant).filter(Tenant.booking_id == payload.booking_id).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Booking already imported")

    tenant = Tenant(**payload.model_dump())
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/tenants/{tenant_id}", response_model=TenantRead)
def get_tenant(tenant_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}/finance")
def get_tenant_finance(tenant_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    items = (
        db.query(Finance)
        .filter(Finance.tenant_id == tenant_id)
        .order_by(Finance.created_at.desc(), Finance.id.desc())
        .all()
    )
    return {
        "tenant": {
            "id": tenant.id,
            "booking_id": tenant.booking_id,
            "name": tenant.name,
        },
        "items": [
            {
                "id": item.id,
                "amount": str(item.amount),
                "currency": item.currency,
                "description": item.description,
                "created_at": item.created_at,
            }
            for item in items
        ],
    }


@router.get("/tenants/{tenant_id}/onedrive")
async def get_tenant_onedrive_files(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    drive_id = os.getenv("MS_GRAPH_DRIVE_ID")
    if not drive_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Microsoft Graph drive is not configured")

    folder_path = _build_one_drive_folder_path(tenant)
    access_token = await _get_graph_access_token()
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:{quote(folder_path, safe='/')}:/children"
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)

    if response.status_code == 404:
        return {"tenant": {"id": tenant.id, "booking_id": tenant.booking_id, "name": tenant.name}, "folder_path": folder_path, "items": []}
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to load Microsoft Graph folder contents")

    payload = response.json()
    items = payload.get("value") if isinstance(payload, dict) else []
    result = []
    for item in items or []:
        if item.get("folder") is not None:
            kind = "folder"
        elif item.get("file") is not None:
            kind = "file"
        else:
            kind = "item"
        result.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "web_url": item.get("webUrl"),
                "kind": kind,
                "size": item.get("size"),
                "last_modified": item.get("lastModifiedDateTime"),
            }
        )

    return {
        "tenant": {
            "id": tenant.id,
            "booking_id": tenant.booking_id,
            "name": tenant.name,
        },
        "folder_path": folder_path,
        "items": result,
    }


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
