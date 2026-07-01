from decimal import Decimal
import logging
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.finance import Finance
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import Beds24BookingPreview, TenantCreate, TenantRead
from app.services.beds24_client import get_booking_detail, get_bookings, get_charges, get_payments

router = APIRouter(tags=["tenants"])
logger = logging.getLogger(__name__)


def _pick_booking_id(item: dict) -> str | None:
    value = item.get("id")
    return str(value) if value is not None and str(value) else None


def _normalize_amount(item: dict) -> Decimal:
    value = item.get("amount") or item.get("value") or item.get("total") or 0
    return Decimal(str(value))


def _extract_guest_fields(item: dict) -> dict:
    gd = item.get("guestDetails") or {}
    if isinstance(gd, list):
        gd = gd[0] if gd else {}
    gd = gd if isinstance(gd, dict) else {}
    logger.warning("RAW item keys: %s", list(item.keys()))
    logger.warning("RAW guestDetails keys: %s | values: %s", list(gd.keys()), dict(gd))

    first_name = str(gd.get("firstName") or gd.get("first_name") or gd.get("firstname") or "").strip() or None
    last_name = str(gd.get("lastName") or gd.get("last_name") or gd.get("lastname") or "").strip() or None
    email = str(gd.get("email") or gd.get("Email") or "").strip() or None
    phone = str(gd.get("tel") or gd.get("phone") or gd.get("telephone") or "").strip() or None
    mobile = str(gd.get("mobile") or gd.get("mobilePhone") or gd.get("cell") or "").strip() or None
    if not first_name and not last_name:
        logger.warning("BEDS24 guestDetails keys: %s | item keys: %s", list(gd.keys()), list(item.keys()))
    check_in = str(item.get("arrival") or "").strip() or None
    check_out = str(item.get("departure") or "").strip() or None
    notes = str(item.get("message") or "").strip() or None
    info_items = item.get("infoItems") or []
    responsible_comm = None
    if isinstance(info_items, list):
        for info in info_items:
            if isinstance(info, dict) and info.get("code") == "QM_CREATED_BY":
                responsible_comm = str(info.get("text") or "").strip() or None
                break
    status_map = {
        0: "Enquiry",
        1: "Confirmed",
        2: "Cancelled by guest",
        3: "Cancelled by property",
        4: "Request",
        5: "Blocked",
        10: "Confirmed (OTA)",
    }
    raw_status = item.get("status")
    try:
        booking_status = status_map.get(int(raw_status), f"Status {raw_status}")
    except (TypeError, ValueError):
        booking_status = str(raw_status).strip() or None
    name_parts = [p for p in [first_name or "", last_name or ""] if p]
    name = " ".join(name_parts) if name_parts else None

    return {
        "first_name": first_name,
        "last_name": last_name,
        "name": name,
        "email": email,
        "phone": phone,
        "mobile": mobile,
        "check_in": check_in,
        "check_out": check_out,
        "booking_status": booking_status,
        "notes": notes,
        "responsible_comm": responsible_comm,
    }


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


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    db.delete(tenant)
    db.commit()


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
        "tenant": {"id": tenant.id, "booking_id": tenant.booking_id, "name": tenant.name},
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
    raw_items = payload.get("value") if isinstance(payload, dict) else []
    result = []
    for item in raw_items or []:
        if item.get("folder") is not None:
            kind = "folder"
        elif item.get("file") is not None:
            kind = "file"
        else:
            kind = "item"
        result.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "web_url": item.get("webUrl"),
            "kind": kind,
            "size": item.get("size"),
            "last_modified": item.get("lastModifiedDateTime"),
        })

    return {
        "tenant": {"id": tenant.id, "booking_id": tenant.booking_id, "name": tenant.name},
        "folder_path": folder_path,
        "items": result,
    }


@router.get("/beds24/bookings", response_model=list[Beds24BookingPreview])
async def beds24_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Beds24BookingPreview]:
    booking_items = await get_bookings()
    results: list[Beds24BookingPreview] = []
    for item in booking_items:
        booking_id = _pick_booking_id(item)
        if not booking_id:
            continue
        fields = _extract_guest_fields(item)
        imported = db.query(Tenant).filter(Tenant.booking_id == booking_id).first() is not None
        results.append(
            Beds24BookingPreview(
                booking_id=booking_id,
                name=fields["name"],
                imported=imported,
                **{k: v for k, v in fields.items() if k != "name"},
            )
        )
    return results


@router.get("/beds24/bookings/{booking_id}/preview", response_model=Beds24BookingPreview)
async def beds24_booking_preview(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Beds24BookingPreview:
    item = await get_booking_detail(booking_id)
    fields = _extract_guest_fields(item)
    imported = db.query(Tenant).filter(Tenant.booking_id == booking_id).first() is not None
    return Beds24BookingPreview(
        booking_id=booking_id,
        name=fields["name"],
        imported=imported,
        **{k: v for k, v in fields.items() if k != "name"},
    )


@router.post("/tenants/import", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def import_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Tenant:
    existing = db.query(Tenant).filter(Tenant.booking_id == payload.booking_id).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Booking already imported")

    tenant = Tenant(**payload.model_dump())
    db.add(tenant)
    db.flush()

    try:
        for item in await get_payments(payload.booking_id):
            db.add(Finance(
                tenant_id=tenant.id,
                amount=_normalize_amount(item),
                currency=item.get("currency") or item.get("currencyCode") or "EUR",
                description=item.get("description") or item.get("type") or "payment",
            ))
    except Exception:
        pass

    try:
        for item in await get_charges(payload.booking_id):
            db.add(Finance(
                tenant_id=tenant.id,
                amount=_normalize_amount(item),
                currency=item.get("currency") or item.get("currencyCode") or "EUR",
                description=item.get("description") or item.get("type") or "charge",
            ))
    except Exception:
        pass

    db.commit()
    db.refresh(tenant)
    return tenant






