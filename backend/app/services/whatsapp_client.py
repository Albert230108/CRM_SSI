import os
from typing import Any

import httpx

WHATSAPP_SERVICE_URL = os.getenv("WHATSAPP_SERVICE_URL")


async def send_whatsapp_message(payload: dict[str, Any]) -> Any:
    if not WHATSAPP_SERVICE_URL:
        raise RuntimeError("WHATSAPP_SERVICE_URL is not set")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(WHATSAPP_SERVICE_URL, json=payload)
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text
