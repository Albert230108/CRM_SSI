from fastapi import APIRouter, Depends, HTTPException, status

from app.core.quotation_token import get_raw_token, verify_quotation_token
from app.schemas.quotation import (
    AdminCostsRequest,
    AdminCostsResponse,
    BuildChargesRequest,
    BuildChargesResponse,
    DiscountRequest,
    DiscountResponse,
    GeneratePdfRequest,
    GeneratePdfResponse,
    SendToBeds24Request,
    VatSplitRequest,
    VatSplitSegment,
)
from app.services import admin_costs as admin_costs_service
from app.services import charge_builder
from app.services import crm_client
from app.services import discount_engine
from app.services import pdf_service
from app.services import tenant_files

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


@router.post("/generate-pdf", response_model=GeneratePdfResponse)
def generate_pdf(
    request: GeneratePdfRequest,
    _token=Depends(verify_quotation_token),
) -> GeneratePdfResponse:
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

    invoice_items = [item.model_dump(by_alias=False) for item in request.invoice_items]
    # pdf_service.process_invoice_items expects Beds24-style keys (qty/amount/vatRate/lineTotal),
    # matching the InvoiceItem schema's snake_case fields translated back here.
    normalized_items = [
        {
            "type": item["type"],
            "description": item["description"],
            "qty": item["qty"],
            "amount": item["amount"],
            "vatRate": item["vat_rate"],
            "status": item.get("status"),
        }
        for item in invoice_items
    ]

    output_path = pdf_service.create_invoice_pdf(
        output_path=next_output.path,
        tenant_name=f"{request.first_name} {request.last_name}",
        booking_number=request.booking_id,
        invoice_items=normalized_items,
        quotation_date=request.quotation_date,
        quotation_number=next_output.quotation_number,
        room_name=request.room_name,
        first_night=request.check_in,
        leaving_day=request.check_out,
        security_deposit=request.security_deposit,
        first_name=request.first_name,
        last_name=request.last_name,
    )

    return GeneratePdfResponse(file_path=str(output_path), quotation_number=next_output.quotation_number)


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
