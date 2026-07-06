import json
import os
from typing import Any
from urllib.parse import urljoin

import httpx

WHATSAPP_SERVICE_URL = os.getenv("WHATSAPP_SERVICE_URL")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY")
WHATSAPP_SERVICE_URL_MAP = os.getenv("WHATSAPP_SERVICE_URL_MAP", "").strip()


def _resolve_service_url(external_account_id: str | None = None, whatsapp_endpoint_id: int | None = None) -> str | None:
    if WHATSAPP_SERVICE_URL_MAP:
        try:
            mapping = json.loads(WHATSAPP_SERVICE_URL_MAP)
            if isinstance(mapping, dict):
                for key in (external_account_id, str(whatsapp_endpoint_id) if whatsapp_endpoint_id is not None else None):
                    if key and str(key) in mapping and str(mapping[str(key)]).strip():
                        return str(mapping[str(key)]).strip()
        except json.JSONDecodeError:
            pass
    return WHATSAPP_SERVICE_URL


async def send_whatsapp_message(payload: dict[str, Any]) -> Any:
    to = payload.get("to")
    message = payload.get("message")
    tenant_id = payload.get("tenant_id")
    external_account_id = payload.get("external_account_id")
    whatsapp_endpoint_id = payload.get("whatsapp_endpoint_id")

    service_url = _resolve_service_url(external_account_id if isinstance(external_account_id, str) else None, whatsapp_endpoint_id if isinstance(whatsapp_endpoint_id, int) else None)
    if not service_url:
        raise RuntimeError("WHATSAPP_SERVICE_URL is not set")
    if not WHATSAPP_API_KEY:
        raise RuntimeError("WHATSAPP_API_KEY is not set")
    if not to:
        raise RuntimeError("WhatsApp payload is missing 'to'")
    if not message:
        raise RuntimeError("WhatsApp payload is missing 'message'")

    url = urljoin(service_url.rstrip("/") + "/", "send")
    request_body = {
        "to": to,
        "message": message,
        "tenant_id": tenant_id,
        "external_account_id": external_account_id,
        "whatsapp_endpoint_id": whatsapp_endpoint_id,
    }
    print("WA DEBUG backend to Node request", {"url": url, "payload": request_body})

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers={"X-API-Key": WHATSAPP_API_KEY},
            json=request_body,
        )
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text
