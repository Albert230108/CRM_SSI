import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services.beds24_service import fetch_booking_with_invoice, update_booking_invoice_items
from app.services.beds24_sync import sync_tenant_from_beds24_booking

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
        }
        for item in request.invoice_items
    ]

    await update_booking_invoice_items(
        booking_id=booking_id,
        original_invoice_item_ids=request.all_original_invoice_item_ids,
        final_invoice_items=final_invoice_items,
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
