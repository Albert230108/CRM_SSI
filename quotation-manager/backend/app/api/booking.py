from fastapi import APIRouter, Depends

from app.core.quotation_token import QuotationTokenPayload, get_raw_token, verify_quotation_token
from app.services import crm_client

router = APIRouter(prefix="/booking", tags=["booking"])


# Registered before the "/{booking_id}" catch-all below so it takes priority for this path.
@router.get("/tenant-context/{tenant_id}")
async def get_tenant_context(
    tenant_id: int,
    _payload: QuotationTokenPayload = Depends(verify_quotation_token),
    token: str = Depends(get_raw_token),
) -> dict:
    return await crm_client.get_tenant_context(tenant_id, token)


@router.get("/group/{booking_id}")
async def get_booking_group(
    booking_id: str,
    _payload: QuotationTokenPayload = Depends(verify_quotation_token),
    token: str = Depends(get_raw_token),
) -> dict:
    return await crm_client.get_beds24_booking_group(booking_id, token)


@router.get("/{booking_id}")
async def get_booking(
    booking_id: str,
    _payload: QuotationTokenPayload = Depends(verify_quotation_token),
    token: str = Depends(get_raw_token),
) -> dict:
    return await crm_client.get_beds24_booking(booking_id, token)
