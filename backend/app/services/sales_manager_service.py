"""Quotation-manager calls for the sales-manager agent.

The sales-manager agent (see ai_agent_orchestrator._run_sales_manager) uses these helpers to
price a stay and render a PDF quotation via the standalone quotation-manager service, exactly the
way the browser does - by minting a scoped quotation token in-process and calling the quotation
backend over HTTP. The generated PDF is filed into the tenant's OneDrive folder by the quotation
service itself; we additionally ask it to return the PDF bytes (include_content) so the reply can
attach the quotation.

This module performs no database writes and does not commit; it only makes network calls and
returns plain data. Persisting the returned PDF as an attachment happens in the caller.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass, field
from datetime import date

import httpx
from fastapi import HTTPException

from app.core.quotation_token import create_quotation_token
from app.models.tenant import Tenant
from app.services import beds24_service

logger = logging.getLogger(__name__)

# Server-to-server base URL for the quotation backend (its API is mounted under /api). On the
# docker-compose network this is the quotation-backend service; override per environment.
QUOTATION_MANAGER_API_URL = os.getenv("QUOTATION_MANAGER_API_URL", "http://quotation-backend:8000").rstrip("/")

_HTTP_TIMEOUT = float(os.getenv("QUOTATION_MANAGER_TIMEOUT_SECONDS", "30"))


class SalesManagerError(Exception):
    """Raised when the quotation service cannot price or render a quotation."""


@dataclass
class SalesQuote:
    nights: int
    total_guests: int
    charges: list[dict]  # each: {kind, description, qty, amount, vat_rate, detail}
    notes: list[str] = field(default_factory=list)


@dataclass
class QuotationPdf:
    content: bytes
    filename: str
    web_url: str | None
    quotation_number: int
    location: str


def _mint_token(tenant: Tenant, issued_by_user_id: int | None) -> str:
    return create_quotation_token(
        tenant_id=tenant.id,
        booking_id=tenant.booking_id,
        issued_by_user_id=issued_by_user_id or 0,
    )


def resolve_quote_params(tenant: Tenant, sales_request: dict) -> dict:
    """Merge the planner's requested parameters with the tenant's booking as fallback.

    The planner supplies the parameters; anything it leaves out falls back to the tenant's own
    booking so a bare `sales_request` still quotes the current stay.
    """
    request = sales_request or {}

    def pick(key: str, fallback):
        value = request.get(key)
        return value if value not in (None, "") else fallback

    return {
        "property_name": pick("property_name", getattr(tenant, "property_name", None)),
        "room_name": pick("room_name", tenant.room_name),
        "check_in": pick("check_in", tenant.check_in),
        "check_out": pick("check_out", tenant.check_out),
        "adults": pick("adults", tenant.num_adults if tenant.num_adults is not None else 1),
        "children": pick("children", tenant.num_children if tenant.num_children is not None else 0),
    }


def _post(path: str, token: str, payload: dict) -> dict:
    url = f"{QUOTATION_MANAGER_API_URL}/api/quotation/{path}"
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise SalesManagerError(f"Quotation service is unreachable: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:300]
        raise SalesManagerError(f"Quotation service returned {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError as exc:  # pragma: no cover - defensive
        raise SalesManagerError("Quotation service returned a non-JSON response") from exc


def compute_charges(tenant: Tenant, params: dict, *, issued_by_user_id: int | None = None) -> SalesQuote:
    """Call build-charges to get the full, factual charge-line stack for the stay."""
    if not params.get("room_name") or not params.get("check_in") or not params.get("check_out"):
        raise SalesManagerError("A quotation needs at least a room and check-in/check-out dates")
    token = _mint_token(tenant, issued_by_user_id)
    body = {
        "property_name": params.get("property_name") or "",
        "room_name": params["room_name"],
        "check_in": params["check_in"],
        "check_out": params["check_out"],
        "adults": int(params.get("adults") or 1),
        "children": int(params.get("children") or 0),
    }
    data = _post("build-charges", token, body)
    return SalesQuote(
        nights=int(data.get("nights") or 0),
        total_guests=int(data.get("total_guests") or 0),
        charges=list(data.get("charges") or []),
        notes=list(data.get("notes") or []),
    )


def charges_to_invoice_items(charges: list[dict]) -> list[dict]:
    """Map build-charges GeneratedCharge lines to the generate-pdf InvoiceItem shape."""
    return [
        {
            "type": "charge",
            "description": charge.get("description") or "",
            "qty": charge.get("qty") or 1,
            "amount": charge.get("amount") or 0,
            "vat_rate": charge.get("vat_rate") or 0,
        }
        for charge in charges
    ]


def fetch_original_invoice_item_ids(tenant: Tenant) -> list[str]:
    """Fetch the ids of every invoice item currently on the tenant's Beds24 booking.

    Beds24 has no "replace invoice items" call (see beds24_service.update_booking_invoice_items):
    the full existing set must be deleted by id before the recomputed set is pushed. This runs
    the async Beds24 fetch via asyncio.run - the same pattern ai_auto_draft_service already uses
    to call send_whatsapp_message from this sync planner-loop call chain, since nothing in that
    chain is itself inside a running event loop.
    """
    if not tenant.booking_id:
        raise SalesManagerError("This tenant has no Beds24 booking to update")
    try:
        booking = asyncio.run(beds24_service.fetch_booking_with_invoice(tenant.booking_id))
    except HTTPException as exc:
        raise SalesManagerError(f"Could not fetch the existing booking from Beds24: {exc.detail}") from exc
    items = booking.get("invoiceItems") or []
    return [str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")]


def build_pending_invoice_update(
    tenant: Tenant, charges: list[dict], original_item_ids: list[str]
) -> dict:
    """The Beds24 invoice-item update payload for this booking, staged on the draft rather than
    pushed here - see ai_agent_orchestrator._run_sales_manager and
    ai_auto_draft_service.send_scheduled_draft, which is the only place this is ever sent."""
    return {
        "booking_id": tenant.booking_id,
        "all_original_invoice_item_ids": original_item_ids,
        "invoice_items": charges_to_invoice_items(charges),
    }


def render_charges_text(quote: SalesQuote) -> str:
    """A compact plain-text rendering of the charge lines, for the sales-manager LLM prompt."""
    lines = [f"Nights: {quote.nights}, guests: {quote.total_guests}"]
    for charge in quote.charges:
        lines.append(
            f"- {charge.get('description', '')}: {charge.get('qty', 1)} x "
            f"{charge.get('amount', 0)} (VAT {charge.get('vat_rate', 0)}%)"
        )
    for note in quote.notes:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def generate_quotation_pdf(
    tenant: Tenant,
    params: dict,
    invoice_items: list[dict],
    *,
    security_deposit: float,
    issued_by_user_id: int | None = None,
) -> QuotationPdf:
    """Render the PDF quotation, file it in the tenant's OneDrive folder, and return its bytes."""
    token = _mint_token(tenant, issued_by_user_id)
    body = {
        "booking_id": tenant.booking_id,
        "first_name": tenant.first_name or "",
        "last_name": tenant.last_name or "",
        "room_name": params.get("room_name") or tenant.room_name or "",
        "property_name": params.get("property_name"),
        "check_in": params.get("check_in") or tenant.check_in or "",
        "check_out": params.get("check_out") or tenant.check_out or "",
        "security_deposit": float(security_deposit or 0),
        "invoice_items": invoice_items,
        "quotation_date": date.today().isoformat(),
        "include_content": True,
    }
    data = _post("generate-pdf", token, body)
    content_base64 = data.get("content_base64")
    if not content_base64:
        raise SalesManagerError("Quotation service did not return the PDF content to attach")
    try:
        content = base64.b64decode(content_base64)
    except (ValueError, TypeError) as exc:
        raise SalesManagerError("Quotation PDF content was not valid base64") from exc
    return QuotationPdf(
        content=content,
        filename=data.get("name") or f"Quotation_{tenant.booking_id}.pdf",
        web_url=data.get("web_url"),
        quotation_number=int(data.get("quotation_number") or 0),
        location=str(data.get("location") or "local"),
    )
