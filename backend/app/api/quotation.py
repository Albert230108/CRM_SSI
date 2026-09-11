import base64
import mimetypes
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.tenants import _extract_room_details
from app.core.dependencies import get_current_user, get_db
from app.core.quotation_token import (
    QUOTATION_TOKEN_EXPIRE_MINUTES,
    QuotationTokenPayload,
    create_quotation_token,
    verify_quotation_token,
)
from app.models.finance import Finance as FinanceRecord
from app.models.tenant import Tenant
from app.models.user import User
from app.services.beds24_service import (
    create_booking,
    fetch_booking_group,
    fetch_booking_with_invoice,
    update_booking_invoice_items,
)
from app.services.beds24_sync import sync_tenant_from_beds24_booking
from app.services import onedrive_service
from app.services import tenant_files_storage

router = APIRouter(tags=["quotation"])

QUOTATION_MANAGER_URL = os.getenv("QUOTATION_MANAGER_URL", "").rstrip("/")


@router.post("/tenants/{tenant_id}/quotation-token")
def mint_quotation_token(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    token = create_quotation_token(
        tenant_id=tenant.id,
        booking_id=tenant.booking_id,
        issued_by_user_id=current_user.id,
    )

    if not QUOTATION_MANAGER_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quotation Manager URL is not configured",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=QUOTATION_TOKEN_EXPIRE_MINUTES)

    # Deep-link straight to this tenant's booking when it has one, so the Quotation
    # Manager opens directly on that quotation instead of its search/home page.
    base_url = f"{QUOTATION_MANAGER_URL}/{quote(tenant.booking_id, safe='')}" if tenant.booking_id else QUOTATION_MANAGER_URL

    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "quotation_url": f"{base_url}?token={token}",
    }


@router.post("/quotation/token")
def mint_tenant_less_quotation_token(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Mints a token scoped to no particular tenant/booking - used by the nav bar's
    "Quotations" button to open the Quotation Manager's home page (search/new
    quotation), as opposed to the tenant-scoped token above which deep-links
    straight into one tenant's editor."""
    token = create_quotation_token(
        tenant_id=None,
        booking_id=None,
        issued_by_user_id=current_user.id,
    )

    if not QUOTATION_MANAGER_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quotation Manager URL is not configured",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=QUOTATION_TOKEN_EXPIRE_MINUTES)

    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "quotation_url": f"{QUOTATION_MANAGER_URL}?token={token}",
    }


@router.get("/quotation/tenant-context/{tenant_id}")
def get_quotation_tenant_context(
    tenant_id: int,
    db: Session = Depends(get_db),
    token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> dict:
    # Unlike the booking-search proxy below, tenant context is pinned to the tenant_id the
    # token was minted for - there's no ad-hoc "browse other tenants" use case for this route.
    if token.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token not valid for this tenant")

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    room_details = _extract_room_details(tenant.beds24_raw or {})
    return {
        "tenant_id": tenant.id,
        "booking_id": tenant.booking_id,
        "name": tenant.name,
        "first_name": tenant.first_name,
        "last_name": tenant.last_name,
        "room_id": tenant.room_id,
        "room_name": tenant.room_name or room_details["room_name"],
        "property_name": tenant.property_name or room_details["property_name"],
        "check_in": tenant.check_in,
        "check_out": tenant.check_out,
    }


@router.get("/quotation/beds24-booking/{booking_id}")
async def get_quotation_beds24_booking(
    booking_id: str,
    _token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> dict:
    # Intentionally not pinned to the token's own booking_id claim - ad-hoc booking search
    # is an explicit feature of the Quotation Manager MVP, so any logged-in-CRM-user-issued
    # token may look up any booking for the duration of its (short) lifetime.
    booking = await fetch_booking_with_invoice(booking_id)
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking


@router.get("/quotation/beds24-booking-group/{booking_id}")
async def get_quotation_beds24_booking_group(
    booking_id: str,
    _token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> dict:
    # Ad-hoc group lookup for the combined-quotation flow; not pinned to the token's
    # own booking_id claim, same rationale as the single-booking GET above.
    bookings = await fetch_booking_group(booking_id)
    master_id = None
    if bookings:
        first = bookings[0]
        group = first.get("bookingGroup") or {}
        master_id = first.get("masterId") or group.get("master") or first.get("id")
    return {"master_id": master_id, "bookings": bookings}


class OneDriveNextNumberRequest(BaseModel):
    booking_id: str
    first_name: str = ""
    last_name: str = ""
    year: int


class OneDriveUploadRequest(OneDriveNextNumberRequest):
    filename: str
    content_base64: str


@router.post("/quotation/onedrive/next-number")
async def quotation_onedrive_next_number(
    request: OneDriveNextNumberRequest,
    db: Session = Depends(get_db),
    _token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> dict:
    access_token, drive_id = await onedrive_service.get_access_token_and_drive_id(db)
    folder = onedrive_service.tenant_folder_path(request.booking_id, request.first_name, request.last_name, request.year)
    names = await onedrive_service.list_child_names(access_token, drive_id, folder)
    prefix = f"Quotation_{request.booking_id}_"
    count = sum(1 for name in names if name.startswith(prefix) and name.endswith(".pdf"))
    return {"next_number": count + 1, "folder_path": folder}


@router.post("/quotation/onedrive/upload")
async def quotation_onedrive_upload(
    request: OneDriveUploadRequest,
    db: Session = Depends(get_db),
    _token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> dict:
    try:
        content = base64.b64decode(request.content_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 PDF content") from exc

    access_token, drive_id = await onedrive_service.get_access_token_and_drive_id(db)
    folder = onedrive_service.tenant_folder_path(request.booking_id, request.first_name, request.last_name, request.year)
    result = await onedrive_service.upload_pdf(access_token, drive_id, folder, request.filename, content)
    return {"name": result["name"], "web_url": result["web_url"], "folder_path": folder}


@router.get("/quotation/tenant-files/search")
def quotation_tenant_files_search(
    q: str | None = None,
    booking_id: str | None = None,
    year: int | None = None,
    tenant_name: str | None = None,
    room: str | None = None,
    _token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> dict:
    # Cross-tenant browse/search for the Quotation Manager's Files page - deliberately not
    # pinned to the token's own tenant_id/booking_id claim, same rationale as the ad-hoc booking
    # lookups above: any logged-in-CRM-user-issued token may search the whole tree.
    entries = tenant_files_storage.search_tenant_files(
        q=q, booking_id=booking_id, year=year, tenant_name=tenant_name, room=room,
    )
    return {
        "items": [
            {"name": e.name, "kind": e.kind, "size": e.size, "relative_path": e.relative_path}
            for e in entries
        ]
    }


@router.get("/quotation/tenant-files/download")
def quotation_tenant_files_download(
    path: str = Query(...),
    _token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> Response:
    resolved = tenant_files_storage.resolve_download_path(path)
    mime_type, _ = mimetypes.guess_type(resolved.name)
    return Response(
        content=resolved.read_bytes(),
        media_type=mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{resolved.name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


class QuotationInvoiceItem(BaseModel):
    type: str
    description: str
    qty: float = 1
    amount: float
    vat_rate: float = 0
    currency: str = "EUR"
    status: str | None = None


class SendInvoiceItemsRequest(BaseModel):
    all_original_invoice_item_ids: list[str]
    invoice_items: list[QuotationInvoiceItem]
    # Optional booking-level updates pushed alongside the invoice items. Each is only sent to
    # Beds24 when provided, so an invoice-items-only push keeps today's behaviour unchanged.
    status: str | None = None
    sub_status: str | None = None
    flag_text: str | None = None


class CreateBookingRequest(BaseModel):
    room_id: int
    arrival: str
    departure: str
    status: str = "inquiry"
    first_name: str
    last_name: str = ""
    email: str = ""
    phone: str = ""
    num_adults: int = 1
    num_children: int = 0
    sub_status: str | None = None
    flag_text: str | None = None
    company_info: str | None = None
    invoice_items: list[QuotationInvoiceItem] = []


# Strip any previously-embedded pay link (HTML anchor or a prior [PAYLINK: ...] tag) so re-sending
# a booking never stacks duplicate links.
_PAYLINK_ANCHOR_RE = re.compile(r"\s*<a\s+href=['\"]?[^>]*bookpay\.php[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
_PAYLINK_TAG_RE = re.compile(r"\s*\[PAYLINK:\s*\[?[-+]?\d+(?:[.,]\d+)?\]?\s*\]", re.IGNORECASE)


def _apply_beds24_paylinks(invoice_items: list[dict]) -> list[dict]:
    """Append Beds24's `[PAYLINK: amount]` tag to each positive payment, so Beds24 renders a real
    pay link on its own guest-facing invoice/emails (it expands the tag server-side using the
    booking's own id - no placeholder round-trip needed). Ported from the desktop's
    _prepare_api_payload_for_beds24: honours the ##NOLINK## marker (preserved on the item so the
    suppression sticks on re-send) and is idempotent - any existing anchor/tag is stripped first.
    """
    for item in invoice_items:
        if item.get("type") != "payment":
            continue
        description = str(item.get("description", "") or "").strip()
        link_disabled = "##NOLINK##" in description
        working = _PAYLINK_TAG_RE.sub("", _PAYLINK_ANCHOR_RE.sub("", description.replace("##NOLINK##", ""))).strip()
        try:
            qty = float(item.get("qty", 1) or 1)
        except (TypeError, ValueError):
            qty = 1.0
        try:
            amount = float(item.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if qty * amount > 0 and not link_disabled:
            working = f"{working} [PAYLINK: {qty * amount:.2f}]".strip()
        item["description"] = f"{working}##NOLINK##" if link_disabled else working
    return invoice_items


@router.post("/quotation/beds24-booking")
async def create_quotation_beds24_booking(
    request: CreateBookingRequest,
    db: Session = Depends(get_db),
    _token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> dict:
    # Creates a brand-new Beds24 booking. Deliberately not pinned to the token's
    # tenant_id/booking_id claim - a New Quotation has no existing tenant yet.
    invoice_items = [
        {
            "type": item.type,
            "description": item.description,
            "qty": item.qty,
            "amount": item.amount,
            "vatRate": item.vat_rate,
            # Payment status ("not paid" or the date actually paid) - omitted for charge
            # rows, which have no meaningful status. Without this, a status typed in the
            # Quotation Manager never reached Beds24 and was lost on the next reload.
            **({"status": item.status} if item.status else {}),
        }
        for item in request.invoice_items
    ]
    _apply_beds24_paylinks(invoice_items)
    payload: dict = {
        "roomId": request.room_id,
        "arrival": request.arrival,
        "departure": request.departure,
        "status": request.status,
        "firstName": request.first_name,
        "lastName": request.last_name,
        "email": request.email,
        "phone": request.phone,
        "numAdult": request.num_adults,
        "numChild": request.num_children,
        "invoiceItems": invoice_items,
    }
    if request.sub_status:
        payload["subStatus"] = request.sub_status
    if request.flag_text:
        payload["flagText"] = request.flag_text
    if request.company_info:
        payload["groupNote"] = request.company_info

    new_booking_id = await create_booking(payload)

    # Re-fetch and materialise the new booking as a Tenant + Finance rows, the same
    # deterministic sync the invoice-items push uses, rather than waiting on a webhook.
    tenant = await sync_tenant_from_beds24_booking(db, new_booking_id)
    if tenant is None:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Beds24 created the booking but it could not be re-fetched to sync the CRM",
        )
    db.commit()

    items = db.query(FinanceRecord).filter(FinanceRecord.tenant_id == tenant.id).order_by(FinanceRecord.created_at.desc(), FinanceRecord.id.desc()).all()
    return {
        "booking_id": new_booking_id,
        "tenant_id": tenant.id,
        "charges": [
            {"id": item.id, "type": item.type, "amount": str(item.amount), "currency": item.currency, "description": item.description}
            for item in items
            if item.type == "charge"
        ],
        "payments": [
            {"id": item.id, "type": item.type, "amount": str(item.amount), "currency": item.currency, "description": item.description}
            for item in items
            if item.type == "payment"
        ],
    }


@router.post("/quotation/beds24-booking/{booking_id}/invoice-items")
async def send_quotation_invoice_items_to_beds24(
    booking_id: str,
    request: SendInvoiceItemsRequest,
    db: Session = Depends(get_db),
    _token: QuotationTokenPayload = Depends(verify_quotation_token),
) -> dict:
    # Beds24 invoiceItems use camelCase keys (qty/amount/vatRate) - translate from the
    # Quotation Manager's snake_case wire format before pushing.
    final_invoice_items = [
        {
            "type": item.type,
            "description": item.description,
            "qty": item.qty,
            "amount": item.amount,
            "vatRate": item.vat_rate,
            # See create_quotation_beds24_booking above - same reasoning for pushing status.
            **({"status": item.status} if item.status else {}),
        }
        for item in request.invoice_items
    ]
    _apply_beds24_paylinks(final_invoice_items)

    booking_fields = {
        "status": request.status,
        "subStatus": request.sub_status,
        "flagText": request.flag_text,
    }
    await update_booking_invoice_items(
        booking_id=booking_id,
        original_invoice_item_ids=request.all_original_invoice_item_ids,
        final_invoice_items=final_invoice_items,
        booking_fields=booking_fields,
    )

    # Re-fetch from Beds24 and rewrite Tenant/Finance deterministically, rather than relying
    # on Beds24 to fire its own webhook back for this API-originated change.
    tenant = await sync_tenant_from_beds24_booking(db, booking_id)
    if tenant is None:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Beds24 accepted the update but the booking could not be re-fetched to sync Finance",
        )
    db.commit()

    items = db.query(FinanceRecord).filter(FinanceRecord.tenant_id == tenant.id).order_by(FinanceRecord.created_at.desc(), FinanceRecord.id.desc()).all()
    return {
        "tenant_id": tenant.id,
        "charges": [
            {"id": item.id, "type": item.type, "amount": str(item.amount), "currency": item.currency, "description": item.description}
            for item in items
            if item.type == "charge"
        ],
        "payments": [
            {"id": item.id, "type": item.type, "amount": str(item.amount), "currency": item.currency, "description": item.description}
            for item in items
            if item.type == "payment"
        ],
    }
