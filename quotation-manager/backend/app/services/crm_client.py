"""HTTP client for calling back into the CRM backend's quotation-proxy
endpoints. Mirrors the CRM's own app/services/whatsapp_client.py pattern:
base URL from an env var, explicit timeouts, and the caller's own bearer
token forwarded unchanged - this service never holds a Beds24 credential
or a CRM login credential of its own.
"""

from typing import Any
from urllib.parse import urlencode

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


async def get_beds24_booking_group(booking_id: str, token: str) -> dict:
    return await _get(f"/api/quotation/beds24-booking-group/{booking_id}", token)


async def send_invoice_items_to_beds24(booking_id: str, token: str, payload: dict) -> dict:
    return await _post(f"/api/quotation/beds24-booking/{booking_id}/invoice-items", token, payload)


async def create_booking(token: str, payload: dict) -> dict:
    return await _post("/api/quotation/beds24-booking", token, payload)


async def onedrive_next_number(token: str, payload: dict) -> dict:
    return await _post("/api/quotation/onedrive/next-number", token, payload)


async def onedrive_upload(token: str, payload: dict) -> dict:
    return await _post("/api/quotation/onedrive/upload", token, payload)


async def list_local_quotes(token: str) -> dict:
    return await _get("/api/quotation/local-quotes", token)


async def save_local_quote(token: str, payload: dict) -> dict:
    return await _post("/api/quotation/local-quotes", token, payload)


async def get_local_quote(token: str, name: str) -> dict:
    from urllib.parse import quote as _urlquote

    return await _get(f"/api/quotation/local-quotes/{_urlquote(name)}", token)


async def search_tenant_files(token: str, params: dict) -> dict:
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    path = "/api/quotation/tenant-files/search"
    return await _get(f"{path}?{query}" if query else path, token)


async def download_tenant_file(relative_path: str, token: str) -> tuple[bytes, str]:
    """Unlike the other calls here, this returns raw bytes (and the upstream content-type)
    rather than parsed JSON - it streams a PDF, not a JSON payload."""
    url = f"{CRM_BACKEND_URL}/api/quotation/tenant-files/download?{urlencode({'path': relative_path})}"
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
    return response.content, response.headers.get("content-type", "application/octet-stream")
