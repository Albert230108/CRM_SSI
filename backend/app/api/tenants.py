from datetime import datetime, timezone
from decimal import Decimal
import logging
import traceback
import re
import os
from urllib.parse import quote
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.finance import Finance as FinanceRecord
from app.models.tenant import Tenant
from app.models.tenant_phone_alias import TenantPhoneAlias
from app.models.user import User
from app.schemas.finance import Finance as FinanceSchema, FinanceItem
from app.schemas.tenant import Beds24BookingPreview, TenantCreate, TenantRead
from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant_conversation_link import TenantConversationLink
from app.services.beds24_client import get_booking_detail, get_bookings
from app.services.beds24_service import fetch_booking_with_invoice
from app.services.tenant_channel_endpoint_lifecycle import delete_tenant_channel_endpoints
from app.services.tenant_phone_aliases import sync_tenant_phone_aliases

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

ROOM_ID_MAPPING = {
    "House": 271050,
    "Studio 1": 262377,
    "Studio 2": 262375,
    "Studio 3": 262379,
    "Studio 4": 262376,
    "Studio 5": 262380,
    "Studio 6": 262378,
    "Room 1": 262576,
    "Room 2": 262578,
    "Room 3": 262579,
    "Room 4": 262580,
    "Room 5": 262581,
    "Under Request": 564014,
    "Ground floor": 389957,
    "Upper floor": 564867,
    "Duplex Apartment": 286739,
}

PROPERTY_ROOMS = {
    "Central-Day Inn": ["Studio 1", "Studio 2", "Studio 3", "Studio 4", "Studio 5", "Studio 6"],
    "Ensche-Day Inn": ["Room 1", "Room 2", "Room 3", "Room 4", "Room 5"],
    "Guest information": ["Under Request"],
    "Hoogstraat 69": ["Ground floor", "Upper floor"],
    "Blekerstraat": ["House"],
    "Atjehstraat": ["Duplex Apartment"],
}

def _extract_room_details(item: dict) -> dict[str, str | int | None]:
    room_name = str(
        item.get("roomName")
        or item.get("room_name")
        or item.get("unitName")
        or item.get("unit_name")
        or item.get("propName")
        or item.get("propertyName")
        or item.get("property_name")
        or item.get("property")
        or item.get("unit")
        or ""
    ).strip() or None
    room_id_raw = item.get("roomId") or item.get("room_id") or item.get("accommodationId") or item.get("accommodation_id") or item.get("unitId") or item.get("unit_id")
    try:
        room_id = int(room_id_raw) if room_id_raw not in (None, "") else None
    except (TypeError, ValueError):
        room_id = None
    property_name = str(
        item.get("propertyName")
        or item.get("property_name")
        or item.get("propName")
        or item.get("property")
        or ""
    ).strip() or None
    if not property_name and room_name:
        property_name = next((property_label for property_label, rooms in PROPERTY_ROOMS.items() if room_name in rooms), None)
    if not room_name and room_id is not None:
        room_name = next((name for name, mapped_id in ROOM_ID_MAPPING.items() if mapped_id == room_id), None)
    return {"room_name": room_name, "room_id": room_id, "property_name": property_name}




def _extract_guest_fields(item: dict) -> dict:
    # Beds24 v2: guest data may be in guestDetails sub-object, guests list, OR top-level.
    gd_raw = item.get("guestDetails") or item.get("guests") or {}
    if isinstance(gd_raw, list):
        gd_raw = gd_raw if gd_raw else {}
    gd: dict = gd_raw if isinstance(gd_raw, dict) else {}

    title = str(gd.get("title") or item.get("title") or "").strip()
    city = str(gd.get("city") or item.get("city") or item.get("guestCity") or "").strip() or None
    country = str(
        gd.get("country")
        or gd.get("countryCode")
        or item.get("country")
        or item.get("countryCode")
        or item.get("guestCountry")
        or ""
    ).strip() or None
    zip_code = str(
        gd.get("zip")
        or gd.get("zipCode")
        or gd.get("postalCode")
        or item.get("zip")
        or item.get("zipCode")
        or item.get("postalCode")
        or ""
    ).strip() or None
    address = str(gd.get("address") or gd.get("street") or item.get("address") or item.get("street") or "").strip() or None
    company = str(
        gd.get("company")
        or gd.get("companyName")
        or item.get("company")
        or item.get("companyName")
        or ""
    ).strip() or None
    language = str(gd.get("language") or gd.get("lang") or item.get("language") or item.get("lang") or "").strip() or None
    num_adults_raw = item.get("numAdult") or item.get("numAdults") or item.get("adults") or 0
    try:
        num_adults = int(num_adults_raw) or None
    except (TypeError, ValueError):
        num_adults = None
    num_children_raw = item.get("numChild") or item.get("numChildren") or item.get("children") or 0
    try:
        num_children = int(num_children_raw) or None
    except (TypeError, ValueError):
        num_children = None
    num_nights_raw = item.get("numNights") or item.get("nights") or 0
    try:
        num_nights = int(num_nights_raw) or None
    except (TypeError, ValueError):
        num_nights = None
    arrival_time = str(item.get("arrivalTime") or item.get("checkInTime") or "").strip() or None
    departure_time = str(item.get("departureTime") or item.get("checkOutTime") or "").strip() or None
    room_details = _extract_room_details(item)
    room_name = room_details["room_name"]
    source = str(item.get("source") or item.get("channel") or item.get("portalId") or "").strip() or None
    referer = str(item.get("referer") or item.get("referralSource") or "").strip() or None
    original_referer = str(item.get("referer2") or "").strip() or None
    try:
        total_price = Decimal(str(item.get("totalPrice") or item.get("price") or item.get("total") or 0)) or None
    except (TypeError, ValueError, ArithmeticError):
        total_price = None
    try:
        commission = Decimal(str(item.get("commission") or 0)) or None
    except (TypeError, ValueError, ArithmeticError):
        commission = None
    try:
        deposit = Decimal(str(item.get("deposit") or 0)) or None
    except (TypeError, ValueError, ArithmeticError):
        deposit = None
    currency = str(item.get("currency") or gd.get("currency") or "").strip() or None
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
    booking_time = str(item.get("bookingTime") or "").strip() or None
    modified_time = str(item.get("modifiedTime") or "").strip() or None
    room_id = room_details["room_id"]
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
        "city": city,
        "country": country,
        "zip_code": zip_code,
        "address": address,
        "company": company,
        "language": language,
        "num_adults": num_adults,
        "num_children": num_children,
        "num_nights": num_nights,
        "arrival_time": arrival_time,
        "departure_time": departure_time,
        "room_name": room_name,
        "source": source,
        "referer": referer,
        "original_referer": original_referer,
        "total_price": total_price,
        "commission": commission,
        "deposit": deposit,
        "currency": currency,
        "booking_status": booking_status,
        "notes": notes,
        "responsible_comm": responsible_comm,
        "room_id": room_id,
        "property_name": room_details["property_name"],
        "booking_time": booking_time,
        "modified_time": modified_time,
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
def list_tenants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: str | None = None,
    status: str | None = None,
    responsible: str | None = None,
    sort_by_message: bool = False,
    sort_desc: bool = True,
) -> list[TenantRead]:
    from sqlalchemy import desc, or_

    query = db.query(Tenant)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Tenant.name.ilike(search_term),
                Tenant.booking_id.ilike(search_term),
                Tenant.email.ilike(search_term),
                Tenant.phone.ilike(search_term),
                Tenant.mobile.ilike(search_term),
            )
        )

    if status:
        query = query.filter(Tenant.booking_status == status)

    if responsible:
        if responsible == "unassigned":
            query = query.filter(Tenant.responsible_comm.is_(None))
        else:
            query = query.filter(Tenant.responsible_comm == responsible)

    query = query.order_by(desc(Tenant.id) if sort_desc else Tenant.id)
    tenants = query.all()
    tenant_ids = [tenant.id for tenant in tenants]

    # Querying the latest Communication/email per tenant one tenant at a time (2 queries x N
    # tenants) meant every tenant-list load did hundreds of sequential DB round trips as the
    # tenant count grew. A window-function query ranks rows per tenant_id in a single pass, so
    # this is 2 queries total regardless of how many tenants there are.
    last_comm_by_tenant_id: dict[int, tuple[datetime, str, str]] = {}
    last_email_by_tenant_id: dict[int, tuple[datetime, str]] = {}
    if tenant_ids:
        from sqlalchemy import func

        comm_ranked = (
            db.query(
                Communication.tenant_id.label("tenant_id"),
                Communication.created_at.label("created_at"),
                Communication.channel.label("channel"),
                Communication.direction.label("direction"),
                func.row_number()
                .over(partition_by=Communication.tenant_id, order_by=Communication.created_at.desc())
                .label("rn"),
            )
            .filter(Communication.tenant_id.in_(tenant_ids))
            .subquery()
        )
        for row in db.query(comm_ranked).filter(comm_ranked.c.rn == 1).all():
            last_comm_by_tenant_id[row.tenant_id] = (row.created_at, row.channel, row.direction)

        email_ranked = (
            db.query(
                TenantConversationLink.tenant_id.label("tenant_id"),
                ConversationMessage.sent_at.label("sent_at"),
                ConversationMessage.direction.label("direction"),
                func.row_number()
                .over(partition_by=TenantConversationLink.tenant_id, order_by=ConversationMessage.sent_at.desc())
                .label("rn"),
            )
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .join(
                TenantConversationLink,
                (TenantConversationLink.conversation_id == Conversation.id)
                & (TenantConversationLink.unlinked_at.is_(None)),
            )
            .filter(TenantConversationLink.tenant_id.in_(tenant_ids))
            .subquery()
        )
        for row in db.query(email_ranked).filter(email_ranked.c.rn == 1).all():
            last_email_by_tenant_id[row.tenant_id] = (row.sent_at, row.direction)

    result = []
    for tenant in tenants:
        candidates: list[tuple[datetime, str, str]] = []
        last_comm = last_comm_by_tenant_id.get(tenant.id)
        if last_comm:
            candidates.append(last_comm)
        last_email = last_email_by_tenant_id.get(tenant.id)
        if last_email:
            candidates.append((last_email[0], "email", last_email[1]))

        tenant_dict = TenantRead.from_orm(tenant).model_dump()
        if candidates:
            last_date, last_channel, last_direction = max(candidates, key=lambda c: c[0])
            tenant_dict["last_message_date"] = last_date
            tenant_dict["last_message_channel"] = last_channel
            tenant_dict["last_message_direction"] = last_direction

        result.append(TenantRead(**tenant_dict))

    if sort_by_message:
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        result.sort(key=lambda t: t.last_message_date or epoch, reverse=sort_desc)

    return result


@router.post("/tenants", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(payload: TenantCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> Tenant:
    existing = db.query(Tenant).filter(Tenant.booking_id == payload.booking_id).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Booking already imported")
    tenant = Tenant(**payload.model_dump())
    db.add(tenant)
    db.flush()
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
    delete_tenant_channel_endpoints(db, tenant_id)
    db.query(TenantPhoneAlias).filter(TenantPhoneAlias.tenant_id == tenant_id).delete(synchronize_session=False)
    db.flush()
    db.delete(tenant)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.exception("Failed to delete tenant %s due to dependent records", tenant_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant could not be deleted because dependent records still exist",
        ) from exc


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
    def _fmt(item: FinanceRecord) -> dict:
        return {
            "id": item.id,
            "type": item.type,
            "amount": str(item.amount),
            "currency": item.currency,
            "description": item.description,
            "created_at": item.created_at,
        }

    room_details = _extract_room_details(tenant.beds24_raw or {})
    return {
        "tenant": {"id": tenant.id, "booking_id": tenant.booking_id, "name": tenant.name, "room_id": tenant.room_id, "room_name": tenant.room_name or room_details["room_name"], "property_name": room_details["property_name"], "check_in": tenant.check_in, "check_out": tenant.check_out, "beds24_raw": tenant.beds24_raw},
        "charges": [_fmt(item) for item in items if item.type == "charge"],
        "payments": [_fmt(item) for item in items if item.type == "payment"],
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
        return {"tenant": {"id": tenant.id, "booking_id": tenant.booking_id, "name": tenant.name, "room_id": tenant.room_id}, "folder_path": folder_path, "items": []}
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

    room_details = _extract_room_details(tenant.beds24_raw or {})
    return {
        "tenant": {"id": tenant.id, "booking_id": tenant.booking_id, "name": tenant.name, "room_id": tenant.room_id, "room_name": tenant.room_name or room_details["room_name"], "property_name": room_details["property_name"], "check_in": tenant.check_in, "check_out": tenant.check_out, "beds24_raw": tenant.beds24_raw},
        "folder_path": folder_path,
        "items": result,
    }


@router.get("/beds24/bookings", response_model=list[Beds24BookingPreview])
async def beds24_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Beds24BookingPreview]:
    try:
        booking_items = await get_bookings()
        results: list[Beds24BookingPreview] = []
        for item in booking_items:
            booking_id = _pick_booking_id(item)
            if not booking_id:
                continue
            fields = _extract_guest_fields(item)
            imported = db.query(Tenant).filter(Tenant.booking_id == booking_id).first() is not None
            try:
                results.append(
                    Beds24BookingPreview(
                        booking_id=booking_id,
                        name=fields["name"],
                        imported=imported,
                        **{k: v for k, v in fields.items() if k != "name"},
                    )
                )
            except ValidationError as exc:
                logger.warning(
                    "Beds24 booking preview validation failed booking_id=%s item_keys=%s error=%s",
                    booking_id,
                    sorted(list(item.keys())) if isinstance(item, dict) else type(item).__name__,
                    exc,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={
                        "error": "beds24_booking_preview_validation_failed",
                        "detail": "Beds24 booking preview data was malformed",
                        "booking_id": booking_id,
                        "error_type": type(exc).__name__,
                    },
                ) from exc
        return results
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Beds24 booking list crashed user_id=%s", getattr(current_user, "id", None))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "unexpected_backend_exception",
                "error_type": type(exc).__name__,
                "detail": "Beds24 booking list crashed",
            },
        ) from exc


@router.get("/beds24/bookings/{booking_id}/preview", response_model=Beds24BookingPreview)
async def beds24_booking_preview(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Beds24BookingPreview:
    try:
        item = await get_booking_detail(booking_id)
        fields = _extract_guest_fields(item)
        imported = db.query(Tenant).filter(Tenant.booking_id == booking_id).first() is not None
        return Beds24BookingPreview(
            booking_id=booking_id,
            name=fields["name"],
            imported=imported,
            **{k: v for k, v in fields.items() if k != "name"},
        )
    except ValidationError as exc:
        logger.warning("Beds24 booking preview validation failed booking_id=%s error=%s", booking_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "beds24_booking_preview_validation_failed",
                "detail": "Beds24 booking preview data was malformed",
                "booking_id": booking_id,
                "error_type": type(exc).__name__,
            },
        ) from exc


async def _import_tenant(
    data: ImportTenantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    booking_id = (data.booking_id or "").strip()
    if not booking_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="booking_id is required")
    logger.info("Beds24 import requested booking_id=%s user_id=%s", booking_id, getattr(current_user, "id", None))
    try:
        booking = await fetch_booking_with_invoice(booking_id)
    except HTTPException as exc:
        detail = str(exc.detail) if exc.detail is not None else "Beds24 import failed"
        status_code = exc.status_code
        if status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            category = "transient_connectivity"
        elif status_code == status.HTTP_401_UNAUTHORIZED:
            category = "credential_issue"
        elif status_code == status.HTTP_400_BAD_REQUEST:
            category = "payload_validation"
        else:
            category = "upstream_api_failure"
        logger.warning(
            "Beds24 import failed booking_id=%s user_id=%s category=%s status=%s detail=%s",
            booking_id,
            getattr(current_user, "id", None),
            category,
            status_code,
            detail,
        )
        raise HTTPException(status_code=status_code, detail={"error": category, "detail": detail, "booking_id": booking_id}) from exc
    except Exception as exc:
        logger.exception(
            "Beds24 import crashed booking_id=%s user_id=%s trace=%s",
            booking_id,
            getattr(current_user, "id", None),
            traceback.format_exc(limit=8),
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error": "unexpected_backend_exception", "detail": "Beds24 import crashed", "booking_id": booking_id}) from exc

    def resolve_placeholders(text: str, booking: dict) -> str:
        """Replace Beds24 template tokens with actual booking values."""
        room_name = str(
            booking.get("roomName") or booking.get("unitName") or booking.get("propName") or ""
        ).strip()
        arrival = str(
            booking.get("arrival") or booking.get("arrivalDate") or booking.get("checkIn") or ""
        ).strip()
        departure = str(
            booking.get("departure") or booking.get("departureDate") or booking.get("checkOut") or ""
        ).strip()

        replacements = {
            "[ROOMNAME1]": room_name,
            "[ROOMNAME2]": room_name,
            "[FIRSTNIGHT]": arrival,
            "[LEAVINGDAY]": departure,
            "[CHECKIN]": arrival,
            "[CHECKOUT]": departure,
            "[BOOKINGID]": str(booking.get("id") or booking_id),
            "[NUMADULTS]": str(booking.get("numAdult") or booking.get("adults") or ""),
            "[NUMCHILDREN]": str(booking.get("numChild") or booking.get("children") or ""),
        }
        for token, value in replacements.items():
            if value:
                text = text.replace(token, value)
        return text

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
    room_name = str(booking.get("roomName") or booking.get("unitName") or booking.get("propName") or "").strip() or None
    room_id = ROOM_ID_MAPPING.get(room_name) if room_name else None
    extracted = _extract_guest_fields(booking)
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
            room_id=room_id,
            city=extracted.get("city"),
            country=extracted.get("country"),
            zip_code=extracted.get("zip_code"),
            address=extracted.get("address"),
            company=extracted.get("company"),
            language=extracted.get("language"),
            num_adults=extracted.get("num_adults"),
            num_children=extracted.get("num_children"),
            num_nights=extracted.get("num_nights"),
            arrival_time=extracted.get("arrival_time"),
            departure_time=extracted.get("departure_time"),
            room_name=extracted.get("room_name"),
            source=extracted.get("source"),
            referer=extracted.get("referer"),
            total_price=extracted.get("total_price"),
            commission=extracted.get("commission"),
            deposit=extracted.get("deposit"),
            currency=extracted.get("currency"),
            beds24_raw=booking,
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
        tenant.room_id = room_id
        tenant.city = extracted.get("city")
        tenant.country = extracted.get("country")
        tenant.zip_code = extracted.get("zip_code")
        tenant.address = extracted.get("address")
        tenant.company = extracted.get("company")
        tenant.language = extracted.get("language")
        tenant.num_adults = extracted.get("num_adults")
        tenant.num_children = extracted.get("num_children")
        tenant.num_nights = extracted.get("num_nights")
        tenant.arrival_time = extracted.get("arrival_time")
        tenant.departure_time = extracted.get("departure_time")
        tenant.room_name = extracted.get("room_name")
        tenant.source = extracted.get("source")
        tenant.referer = extracted.get("referer")
        tenant.total_price = extracted.get("total_price")
        tenant.commission = extracted.get("commission")
        tenant.deposit = extracted.get("deposit")
        tenant.currency = extracted.get("currency")
        tenant.beds24_raw = booking

    sync_tenant_phone_aliases(db, tenant, primary_phone=tenant.phone, alias_phones=[tenant.mobile])

    db.query(FinanceRecord).filter(FinanceRecord.tenant_id == tenant.id).delete(synchronize_session=False)

    charges: list[FinanceItem] = []
    payments: list[FinanceItem] = []
    for item in booking.get("invoiceItems", []) or []:
        if not isinstance(item, dict):
            continue
        cleaned = resolve_placeholders(
            clean_description(item.get("description", "")),
            booking
        )
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
                    type=item_type,
                    amount=Decimal(str(line_total)),
                    currency=str(item.get("currency") or "EUR"),
                    description=cleaned,
                )
            )

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Beds24 import database commit failed booking_id=%s tenant_id=%s user_id=%s",
            booking_id,
            getattr(tenant, 'id', None),
            getattr(current_user, 'id', None),
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error": "database_error", "detail": "Failed to persist imported tenant", "booking_id": booking_id, "tenant_id": getattr(tenant, 'id', None)}) from exc
    db.refresh(tenant)

    logger.info("Beds24 import completed booking_id=%s tenant_id=%s user_id=%s", booking_id, tenant.id, getattr(current_user, 'id', None))

    return {
        "success": True,
        "tenant_id": tenant.id,
        "booking_id": data.booking_id,
        "charges_imported": len(charges),
        "payments_imported": len(payments),
    }


@router.post("/tenants/import")
async def import_tenant(
    data: ImportTenantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await _import_tenant(data=data, db=db, current_user=current_user)


@router.post("/beds24/bookings")
async def import_beds24_booking(
    data: ImportTenantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await _import_tenant(data=data, db=db, current_user=current_user)



