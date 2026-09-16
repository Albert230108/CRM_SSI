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

import logging
import os
from dataclasses import dataclass, field
from datetime import date

import httpx

from app.core.quotation_token import create_quotation_token
from app.models.tenant import Tenant

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
    # Relative to TENANT_FILES_ROOT (the shared mount the quotation-manager writes into) - see
    # app.services.tenant_files_storage.resolve_download_path, which the caller uses to read the
    # bytes lazily at send time rather than shipping them through this API call.
    file_path: str
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


def build_pending_execution(
    tenant: Tenant,
    action: str,
    charges: list[dict],
    params: dict,
    planner_request: dict,
) -> dict:
    """The data-only Beds24 write the sales manager prepared, handed to the executor agent for
    validation and (once approved) the actual push - see ai_agent_orchestrator._run_executor and
    ai_auto_draft_service._execute_pending. The sales manager itself never touches Beds24: this is
    the entire handoff object, built from data already computed locally (never sent here).

    action="update_quotation" -> update this tenant's existing Beds24 booking's invoice items.
    action="create_quotation" -> create a brand-new Beds24 booking from the quoted stay. The
    executor blocks with a clear reason if room_id is missing rather than guessing one - see
    ai_auto_draft_service._execute_pending.
    """
    if action == "create_quotation":
        return {
            "action": "create",
            "create_payload": {
                "room_id": planner_request.get("room_id"),
                "arrival": params.get("check_in"),
                "departure": params.get("check_out"),
                "status": "inquiry",
                "first_name": planner_request.get("guest_first_name") or tenant.first_name or "",
                "last_name": planner_request.get("guest_last_name") or tenant.last_name or "",
                "email": planner_request.get("guest_email") or tenant.email or "",
                "phone": planner_request.get("guest_phone") or "",
                "num_adults": int(params.get("adults") or 1),
                "num_children": int(params.get("children") or 0),
                "invoice_items": charges_to_invoice_items(charges),
            },
        }
    return {
        "action": "update",
        "booking_id": tenant.booking_id,
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
    """Render the PDF quotation and file it in the tenant's folder.

    Requests include_content=False: the quotation-manager and this backend share the
    TENANT_FILES_ROOT mount, so the caller reads the bytes lazily by path
    (tenant_files_storage.resolve_download_path) at send time instead of shipping them through
    this S2S call.
    """
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
        "include_content": False,
    }
    data = _post("generate-pdf", token, body)
    file_path = data.get("file_path")
    if not file_path or str(data.get("location") or "local") != "local":
        raise SalesManagerError("Quotation service did not return a local file path to attach")
    return QuotationPdf(
        file_path=str(file_path),
        filename=data.get("name") or f"Quotation_{tenant.booking_id}.pdf",
        web_url=data.get("web_url"),
        quotation_number=int(data.get("quotation_number") or 0),
        location=str(data.get("location") or "local"),
    )
