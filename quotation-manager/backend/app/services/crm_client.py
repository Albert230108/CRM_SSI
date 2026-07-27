"""HTTP client for calling back into the CRM backend's quotation-proxy
endpoints. Mirrors the CRM's own app/services/whatsapp_client.py pattern:
base URL from an env var, explicit timeouts, and the caller's own bearer
token forwarded unchanged - this service never holds a Beds24 credential
or a CRM login credential of its own.
"""

from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import CRM_BACKEND_URL

_TIMEOUT = httpx.Timeout(30.0)


class CrmClientError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


async def _get(path: str, token: str) -> Any:
    url = f"{CRM_BACKEND_URL}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"CRM backend unavailable: {exc}",
            ) from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


async def _post(path: str, token: str, json_body: Any) -> Any:
    url = f"{CRM_BACKEND_URL}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=json_body)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"CRM backend unavailable: {exc}",
            ) from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


async def get_tenant_context(tenant_id: int, token: str) -> dict:
    return await _get(f"/api/quotation/tenant-context/{tenant_id}", token)


async def get_beds24_booking(booking_id: str, token: str) -> dict:
    return await _get(f"/api/quotation/beds24-booking/{booking_id}", token)


async def send_invoice_items_to_beds24(booking_id: str, token: str, payload: dict) -> dict:
    return await _post(f"/api/quotation/beds24-booking/{booking_id}/invoice-items", token, payload)
