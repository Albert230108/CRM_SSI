from decimal import Decimal
import logging
import re
import os
from urllib.parse import quote
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.finance import Finance as FinanceRecord
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.finance import Finance as FinanceSchema, FinanceItem
from app.schemas.tenant import Beds24BookingPreview, TenantCreate, TenantRead
from app.services.beds24_client import get_booking_detail, get_bookings
from app.services.beds24_service import fetch_booking_with_invoice

router = APIRouter(tags=["tenants"])
logger = logging.getLogger(__name__)


class ImportTenantRequest(BaseModel):
    booking_id: str
    name: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    check_in: str
    check_out: str
    notes: Optional[str] = None
    booking_status: Optional[str] = "confirmed"
    responsible_comm: Optional[str] = None


def _pick_booking_id(item: dict) -> str | None:
    value = item.get("id")
    return str(value) if value is not None and str(value) else None


def _normalize_amount(item: dict) -> Decimal:
    value = item.get("amount") or item.get("value") or item.get("total") or 0
    return Decimal(str(value))


def _extract_guest_fields(item: dict) -> dict:
    # Beds24 v2: guest data may be in guestDetails sub-object, guests list, OR top-level.
    gd_raw = item.get("guestDetails") or item.get("guests") or {}
    if isinstance(gd_raw, list):
        gd_raw = gd_raw if gd_raw else {}
    gd: dict = gd_raw if isinstance(gd_raw, dict) else {}

    title = str(gd.get("title") or item.get("title") or "").strip()
    first_name = str(
        gd.get("firstName")
        or gd.get("firstname")
        or item.get("firstName")
        or item.get("firstname")
        or item.get("guestFirstName")
        or ""
    ).strip() or None
    last_name = str(
        gd.get("lastName")
        or gd.get("lastname")
        or item.get("lastName")
        or item.get("lastname")
        or item.get("guestLastName")
        or ""
    ).strip() or None
    name_parts = [p for p in [title, first_name or "", last_name or ""] if p]
    name = " ".join(name_parts).strip() or str(
        gd.get("fullName")
        or item.get("fullName")
        or item.get("name")
        or item.get("guestName")
        or ""
    ).strip() or None

    email = str(
        gd.get("email")
        or gd.get("Email")
        or item.get("email")
        or item.get("guestEmail")
        or ""
    ).strip() or None
    phone = str(
        gd.get("phone")
        or gd.get("telephone")
        or gd.get("tel")
        or item.get("phone")
        or item.get("telephone")
        or item.get("tel")
        or item.get("guestPhone")
        or ""
    ).strip() or None
    mobile = str(
        gd.get("mobile")
        or gd.get("mobilePhone")
        or gd.get("cellPhone")
        or item.get("mobile")
        or item.get("mobilePhone")
        or item.get("cellPhone")
        or item.get("guestMobile")
        or ""
    ).strip() or None
    check_in = str(item.get("arrival") or item.get("checkIn") or item.get("arrivalDate") or "").strip() or None
    check_out = str(item.get("departure") or item.get("checkOut") or item.get("departureDate") or "").strip() or None
    notes = str(item.get("comments") or item.get("comment") or item.get("note") or item.get("message") or "").strip() or None
    info_items = item.get("infoItems") or item.get("infoCodes") or []
    responsible_comm = None
    if isinstance(info_items, list):
        for info in info_items:
            if isinstance(info, dict) and info.get("code") == "QM_CREATED_BY":
                responsible_comm = str(info.get("text") or info.get("description") or "").strip() or None
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
    if not first_name and not last_name and not name:
        logger.warning(
            "BEDS24 no guest name. item keys=%s | guestDetails keys=%s | guestDetails=%s",
            list(item.keys()),
            list(gd.keys()),
            dict(gd),
        )

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
        db.query(FinanceRecord)
        .filter(FinanceRecord.tenant_id == tenant_id)
        .order_by(FinanceRecord.created_at.desc(), FinanceRecord.id.desc())
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


@router.post("/tenants/import")
async def import_tenant(
    data: ImportTenantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    booking_id = data.booking_id
    booking = await fetch_booking_with_invoice(booking_id)

    def clean_description(desc: str) -> str:
        desc = re.sub(r"<a[^>]*>.*?</a>", "", str(desc or ""), flags=re.DOTALL)
        desc = desc.replace("##NOLINK##", "").strip()
        return desc

    first_name = (data.first_name or "").strip() or None
    last_name = (data.last_name or "").strip() or None
    name = (data.name or "").strip() or booking_id
    email = (data.email or "").strip() or None
    phone = (data.phone or "").strip() or None
    mobile = (data.mobile or "").strip() or None
    check_in = (data.check_in or "").strip() or None
    check_out = (data.check_out or "").strip() or None
    notes = (data.notes or "").strip() or None
    booking_status = (data.booking_status or "confirmed").strip() or "confirmed"
    responsible_comm = (data.responsible_comm or "").strip() or None

    existing = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
    if existing is None:
        tenant = Tenant(
            booking_id=booking_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            mobile=mobile,
            check_in=check_in,
            check_out=check_out,
            notes=notes,
            booking_status=booking_status,
            name=name,
            responsible_comm=responsible_comm,
        )
        db.add(tenant)
        db.flush()
    else:
        tenant = existing
        tenant.first_name = first_name
        tenant.last_name = last_name
        tenant.email = email
        tenant.phone = phone
        tenant.mobile = mobile
        tenant.check_in = check_in
        tenant.check_out = check_out
        tenant.notes = notes
        tenant.booking_status = booking_status
        tenant.name = name
        tenant.responsible_comm = responsible_comm

    db.query(FinanceRecord).filter(FinanceRecord.tenant_id == tenant.id).delete(synchronize_session=False)

    charges: list[FinanceItem] = []
    payments: list[FinanceItem] = []
    for item in booking.get("invoiceItems", []) or []:
        if not isinstance(item, dict):
            continue
        cleaned = clean_description(item.get("description", ""))
        line_qty = item.get("qty", 1) or 1
        line_amount = item.get("amount", 0) or 0
        line_total = Decimal(str(line_amount)) * Decimal(str(line_qty))
        vat_rate = Decimal(str(item.get("vatRate", 0) or 0))
        vat_amount = line_total * (vat_rate / Decimal("100"))
        record = {
            "beds24_item_id": item.get("id"),
            "description": cleaned,
            "qty": line_qty,
            "amount": line_amount,
            "line_total": line_total,
            "vat_rate": vat_rate,
            "vat_amount": vat_amount,
            "status": item.get("status", ""),
        }
        item_type = str(item.get("type") or "").lower()
        if item_type == "charge":
            charges.append(FinanceItem(**record, type=item_type))
        elif item_type == "payment":
            payments.append(FinanceItem(**record, type=item_type))
        if item_type in {"charge", "payment"}:
            db.add(
                FinanceRecord(
                    tenant_id=tenant.id,
                    amount=Decimal(str(line_total)),
                    currency=str(item.get("currency") or "EUR"),
                    description=cleaned,
                )
            )

    db.commit()
    db.refresh(tenant)

    return {
        "success": True,
        "tenant_id": tenant.id,
        "booking_id": data.booking_id,
        "charges_imported": len(charges),
        "payments_imported": len(payments),
    }
