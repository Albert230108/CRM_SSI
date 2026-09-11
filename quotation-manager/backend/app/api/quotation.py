import base64
import pathlib
import tempfile
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.config import ONEDRIVE_STORAGE_ENABLED
from app.core.quotation_token import get_raw_token, verify_quotation_token
from app.schemas.quotation import (
    AdminCostsRequest,
    AdminCostsResponse,
    BuildChargesRequest,
    BuildChargesResponse,
    CreateBookingRequest,
    DiscountRequest,
    DiscountResponse,
    GeneratePdfRequest,
    GeneratePdfResponse,
    PaymentPlanRequest,
    PaymentPlanResponse,
    SendToBeds24Request,
    VatSplitRequest,
    VatSplitSegment,
)
from app.services import admin_costs as admin_costs_service
from app.services import charge_builder
from app.services import crm_client
from app.services import discount_engine
from app.services import payment_plan as payment_plan_service
from app.services import pdf_service
from app.services import tenant_files
from app.services import vat

router = APIRouter(prefix="/quotation", tags=["quotation"])


@router.post("/discount", response_model=DiscountResponse)
def calculate_discount(
    request: DiscountRequest,
    _token=Depends(verify_quotation_token),
) -> DiscountResponse:
    pricing_data = discount_engine.load_pricing_data()
    result = discount_engine.calculate_discount_for_booking(
        room_name=request.room_name,
        property_name=request.property_name,
        nights=request.nights,
        checkin_date=request.checkin_date,
        base_price_per_night=0.0,
        pricing_data=pricing_data,
    )
    # Settings/the discount engine stay ex-VAT; add incl.-VAT figures purely for
    # the quotation form's display, same rate the generated charge lines use.
    rate = vat.vat_rate_for_date(request.checkin_date or date.today())
    result = {
        **result,
        "vat_rate": rate,
        "original_price_incl_vat": vat.gross_amount(result["original_price"], rate),
        "discounted_price_incl_vat": vat.gross_amount(result["discounted_price"], rate),
    }
    return DiscountResponse(**result)


@router.post("/admin-costs", response_model=AdminCostsResponse)
def calculate_admin_costs(
    request: AdminCostsRequest,
    _token=Depends(verify_quotation_token),
) -> AdminCostsResponse:
    result = admin_costs_service.calculate_admin_costs(
        property_name=request.property_name,
        total_charges=request.total_charges,
        deposit_amount=request.deposit_amount,
        city_tax_amount=request.city_tax_amount,
    )
    return AdminCostsResponse(**result)


@router.post("/vat-split", response_model=list[VatSplitSegment])
def calculate_vat_split(
    request: VatSplitRequest,
    _token=Depends(verify_quotation_token),
) -> list[VatSplitSegment]:
    segments = pdf_service.split_booking_by_vat(request.start_date, request.end_date, request.price_per_night)
    return [VatSplitSegment(**segment) for segment in segments]


def _normalized_invoice_items(request: GeneratePdfRequest) -> list[dict]:
    # pdf_service.process_invoice_items expects Beds24-style keys (qty/amount/vatRate),
    # matching the InvoiceItem schema's snake_case fields translated back here.
    return [
        {
            "type": item.type,
            "description": item.description,
            "qty": item.qty,
            "amount": item.amount,
            "vatRate": item.vat_rate,
            "status": item.status,
        }
        for item in request.invoice_items
    ]


def _render_pdf(request: GeneratePdfRequest, output_path: pathlib.Path, quotation_number: int) -> None:
    pdf_service.create_invoice_pdf(
        output_path=output_path,
        tenant_name=f"{request.first_name} {request.last_name}",
        booking_number=request.booking_id,
        invoice_items=_normalized_invoice_items(request),
        quotation_date=request.quotation_date,
        quotation_number=quotation_number,
        room_name=request.room_name,
        first_night=request.check_in,
        leaving_day=request.check_out,
        security_deposit=request.security_deposit,
        first_name=request.first_name,
        last_name=request.last_name,
        override_price_per_night=request.override_price_per_night,
        override_total_nights=request.override_total_nights,
    )


def _generate_pdf_local(request: GeneratePdfRequest) -> GeneratePdfResponse:
    """Fallback: write the PDF to the mounted TENANT_FILES_ROOT folder (the original
    behaviour), used when Microsoft Graph/OneDrive is not configured on the CRM."""
    folder = tenant_files.create_booking_folder(
        booking_id=request.booking_id,
        first_name=request.first_name,
        last_name=request.last_name,
        arrival_date_str=request.check_in,
    )
    next_output = tenant_files.next_quotation_output_path(
        folder=folder,
        booking_id=request.booking_id,
        room_label=request.room_name,
        tenant_name=f"{request.first_name} {request.last_name}",
        checkin_date_str=request.check_in,
        checkout_date_str=request.check_out,
    )
    _render_pdf(request, next_output.path, next_output.quotation_number)
    content_base64 = None
    if request.include_content:
        content_base64 = base64.b64encode(next_output.path.read_bytes()).decode("ascii")
    return GeneratePdfResponse(
        file_path=str(next_output.path),
        quotation_number=next_output.quotation_number,
        location="local",
        content_base64=content_base64,
    )


def _peek_local_next_number(request: GeneratePdfRequest) -> int:
    """Best-effort quotation-number guess for a download: counts whatever's
    already in the local tenant folder, WITHOUT creating it or writing
    anything - used as the download fallback when OneDrive/Graph can't be
    reached, and for a New-Quotation draft, which has no real booking (or
    folder) yet and so always comes back 1."""
    try:
        folder = tenant_files.resolve_booking_folder_path(
            booking_id=request.booking_id,
            first_name=request.first_name,
            last_name=request.last_name,
            arrival_date_str=request.check_in,
        )
        return tenant_files.next_quotation_output_path(
            folder=folder,
            booking_id=request.booking_id,
            room_label=request.room_name,
            tenant_name=f"{request.first_name} {request.last_name}",
            checkin_date_str=request.check_in,
            checkout_date_str=request.check_out,
        ).quotation_number
    except tenant_files.TenantFolderError:
        return 1


async def _generate_pdf_download(request: GeneratePdfRequest, token: str) -> GeneratePdfResponse:
    """delivery="download": render the PDF and hand the bytes straight back -
    nothing is written to OneDrive or the local tenant folder. A "Draft"
    booking_id (New Quotation's PDF preview, before any booking exists) always
    skips the OneDrive lookup outright, since there is no real folder to ask about."""
    quotation_number = 1
    if request.booking_id != "Draft":
        try:
            year = datetime.strptime(request.check_in, "%Y-%m-%d").year
        except ValueError:
            year = datetime.now().year
        identity = {
            "booking_id": request.booking_id,
            "first_name": request.first_name,
            "last_name": request.last_name,
            "year": year,
        }
        try:
            number_info = await crm_client.onedrive_next_number(token, identity)
            quotation_number = int(number_info["next_number"])
        except HTTPException:
            quotation_number = _peek_local_next_number(request)
    else:
        quotation_number = _peek_local_next_number(request)

    filename = tenant_files.build_quotation_filename(
        booking_id=request.booking_id,
        quotation_number=quotation_number,
        room_label=request.room_name,
        tenant_name=f"{request.first_name} {request.last_name}",
        checkin_date_str=request.check_in,
        checkout_date_str=request.check_out,
    )

    with tempfile.TemporaryDirectory() as tmp:
        temp_path = pathlib.Path(tmp) / filename
        _render_pdf(request, temp_path, quotation_number)
        content = temp_path.read_bytes()

    return GeneratePdfResponse(
        file_path=filename,
        quotation_number=quotation_number,
        location="download",
        name=filename,
        content_base64=base64.b64encode(content).decode("ascii"),
    )


@router.post("/generate-pdf", response_model=GeneratePdfResponse)
async def generate_pdf(
    request: GeneratePdfRequest,
    _payload=Depends(verify_quotation_token),
    token: str = Depends(get_raw_token),
) -> GeneratePdfResponse:
    if request.delivery == "download":
        return await _generate_pdf_download(request, token)

    # Local storage is the active path by default (ONEDRIVE_STORAGE_ENABLED=false) - quotations
    # are filed straight to the mounted TENANT_FILES_ROOT folder, the same as the 503 fallback
    # below. The OneDrive/Graph branch is left in place, untouched, for whoever re-enables it.
    if not ONEDRIVE_STORAGE_ENABLED:
        return _generate_pdf_local(request)

    try:
        year = datetime.strptime(request.check_in, "%Y-%m-%d").year
    except ValueError:
        year = datetime.now().year

    identity = {
        "booking_id": request.booking_id,
        "first_name": request.first_name,
        "last_name": request.last_name,
        "year": year,
    }

    # Preferred path: upload the PDF into the tenant's OneDrive folder via the CRM's
    # Microsoft Graph integration. Falls back to the local mounted folder only when
    # the CRM reports Graph is not configured (503).
    try:
        number_info = await crm_client.onedrive_next_number(token, identity)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            return _generate_pdf_local(request)
        raise

    quotation_number = int(number_info["next_number"])
    filename = tenant_files.build_quotation_filename(
        booking_id=request.booking_id,
        quotation_number=quotation_number,
        room_label=request.room_name,
        tenant_name=f"{request.first_name} {request.last_name}",
        checkin_date_str=request.check_in,
        checkout_date_str=request.check_out,
    )

    with tempfile.TemporaryDirectory() as tmp:
        temp_path = pathlib.Path(tmp) / filename
        _render_pdf(request, temp_path, quotation_number)
        content = temp_path.read_bytes()

    content_base64 = base64.b64encode(content).decode("ascii")
    upload = await crm_client.onedrive_upload(
        token,
        {**identity, "filename": filename, "content_base64": content_base64},
    )
    return GeneratePdfResponse(
        file_path=upload.get("web_url") or upload.get("folder_path") or filename,
        quotation_number=quotation_number,
        location="onedrive",
        web_url=upload.get("web_url"),
        name=upload.get("name") or filename,
        content_base64=content_base64 if request.include_content else None,
    )


@router.post("/build-charges", response_model=BuildChargesResponse)
def build_charges(
    request: BuildChargesRequest,
    _token=Depends(verify_quotation_token),
) -> BuildChargesResponse:
    pricing_data = discount_engine.load_pricing_data()
    try:
        result = charge_builder.build_standard_charges(
            property_name=request.property_name,
            room_name=request.room_name,
            checkin_date=request.check_in,
            checkout_date=request.check_out,
            adults=request.adults,
            children=request.children,
            quotation_flag=request.quotation_flag,
            pricing_data=pricing_data,
        )
    except charge_builder.ChargeBuilderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BuildChargesResponse(**result)


@router.post("/build-payment-plan", response_model=PaymentPlanResponse)
def build_payment_plan(
    request: PaymentPlanRequest,
    _token=Depends(verify_quotation_token),
) -> PaymentPlanResponse:
    charge_lines = [
        payment_plan_service.ChargeLine(description=c.description, qty=c.qty, amount=c.amount)
        for c in request.charges
    ]
    existing_payments = [
        payment_plan_service.PaymentRow(
            description=p.description, qty=p.qty, amount=p.amount, status=p.status, vat_rate=p.vat_rate
        )
        for p in request.existing_payments
    ]
    try:
        result = payment_plan_service.build_payment_plan(
            charges=charge_lines,
            check_in=request.check_in,
            check_out=request.check_out,
            installments=request.installments,
            security_deposit=request.security_deposit,
            existing_payments=existing_payments,
        )
    except payment_plan_service.PaymentPlanError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PaymentPlanResponse(**result)


@router.post("/create-booking")
async def create_booking(
    request: CreateBookingRequest,
    _payload=Depends(verify_quotation_token),
    token: str = Depends(get_raw_token),
) -> dict:
    payload = request.model_dump()
    return await crm_client.create_booking(token, payload)


@router.get("/tenant-files/search")
async def quotation_tenant_files_search(
    q: str | None = None,
    booking_id: str | None = None,
    year: int | None = None,
    tenant_name: str | None = None,
    room: str | None = None,
    _payload=Depends(verify_quotation_token),
    token: str = Depends(get_raw_token),
) -> dict:
    """The Files page's cross-tenant browse/search - proxies straight to the CRM, which owns
    the mounted TENANT_FILES_ROOT tree (app.services.tenant_files_storage on that side)."""
    return await crm_client.search_tenant_files(
        token, {"q": q, "booking_id": booking_id, "year": year, "tenant_name": tenant_name, "room": room}
    )


@router.get("/tenant-files/download")
async def quotation_tenant_files_download(
    path: str,
    _payload=Depends(verify_quotation_token),
    token: str = Depends(get_raw_token),
) -> Response:
    content, content_type = await crm_client.download_tenant_file(path, token)
    filename = path.rsplit("/", 1)[-1]
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{booking_id}/send-to-beds24")
async def send_to_beds24(
    booking_id: str,
    request: SendToBeds24Request,
    _payload=Depends(verify_quotation_token),
    token: str = Depends(get_raw_token),
) -> dict:
    payload = {
        "all_original_invoice_item_ids": request.all_original_invoice_item_ids,
        "invoice_items": [item.model_dump() for item in request.invoice_items],
    }
    return await crm_client.send_invoice_items_to_beds24(booking_id, token, payload)
