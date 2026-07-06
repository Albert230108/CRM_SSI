import os
from typing import Any
from urllib.parse import urljoin

import httpx

WHATSAPP_SERVICE_URL = os.getenv("WHATSAPP_SERVICE_URL")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY")


async def send_whatsapp_message(payload: dict[str, Any]) -> Any:
    if not WHATSAPP_SERVICE_URL:
        raise RuntimeError("WHATSAPP_SERVICE_URL is not set")
    if not WHATSAPP_API_KEY:
        raise RuntimeError("WHATSAPP_API_KEY is not set")

    to = payload.get("to")
    message = payload.get("message")
    tenant_id = payload.get("tenant_id")
    if not to:
        raise RuntimeError("WhatsApp payload is missing 'to'")
    if not message:
        raise RuntimeError("WhatsApp payload is missing 'message'")

    url = urljoin(WHATSAPP_SERVICE_URL.rstrip("/") + "/", "send")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers={"X-API-Key": WHATSAPP_API_KEY},
            json={"to": to, "message": message, "tenant_id": tenant_id},
        )
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text