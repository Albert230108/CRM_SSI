import json
import os
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import status

WHATSAPP_SERVICE_URL = os.getenv("WHATSAPP_SERVICE_URL")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY")
WHATSAPP_SERVICE_URL_MAP = os.getenv("WHATSAPP_SERVICE_URL_MAP", "").strip()


class WhatsAppBridgeError(RuntimeError):
    def __init__(self, status_code: int, message: str, response_body: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


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
    attachments = payload.get("attachments") or []

    service_url = _resolve_service_url(external_account_id if isinstance(external_account_id, str) else None, whatsapp_endpoint_id if isinstance(whatsapp_endpoint_id, int) else None)
    if not service_url:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge URL is not configured")
    if not WHATSAPP_API_KEY:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge API key is not configured")
    if not to:
        raise WhatsAppBridgeError(status.HTTP_400_BAD_REQUEST, "WhatsApp payload is missing 'to'")
    if not message and not attachments:
        raise WhatsAppBridgeError(status.HTTP_400_BAD_REQUEST, "WhatsApp payload is missing 'message'")

    url = urljoin(service_url.rstrip("/") + "/", "send")
    request_body = {
        "to": to,
        "message": message,
        "tenant_id": tenant_id,
        "external_account_id": external_account_id,
        "whatsapp_endpoint_id": whatsapp_endpoint_id,
        "attachments": attachments,
    }
    print(
        "WA DEBUG backend to Node request",
        {
            "url": url,
            "tenant_id": tenant_id,
            "external_account_id": external_account_id,
            "whatsapp_endpoint_id": whatsapp_endpoint_id,
            "to": to,
            "message_length": len(str(message)),
            "attachment_count": len(attachments),
        },
    )

    # Attachments are base64 in the body (the bridge runs on the host, so it can't read the
    # backend container's attachment volume) - 25MB of files is ~33MB of base64, which the
    # default 10s write timeout cannot push on a slow link.
    if attachments:
        timeout = httpx.Timeout(connect=5.0, read=120.0, write=120.0, pool=5.0)
    else:
        timeout = httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers={"X-API-Key": WHATSAPP_API_KEY},
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        print(
            "WA DEBUG backend bridge timeout",
            {
                "url": url,
                "tenant_id": tenant_id,
                "external_account_id": external_account_id,
                "whatsapp_endpoint_id": whatsapp_endpoint_id,
                "error": exc.__class__.__name__,
            },
        )
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge request timed out") from exc
    except httpx.RequestError as exc:
        print(
            "WA DEBUG backend bridge unavailable",
            {
                "url": url,
                "tenant_id": tenant_id,
                "external_account_id": external_account_id,
                "whatsapp_endpoint_id": whatsapp_endpoint_id,
                "error": exc.__class__.__name__,
            },
        )
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge is unavailable") from exc

    content_type = response.headers.get("content-type", "")
    if not response.is_success:
        response_body: Any | None = None
        error_message = "Failed to send WhatsApp message"
        if content_type.startswith("application/json"):
            try:
                response_body = response.json()
            except ValueError as exc:
                print(
                    "WA DEBUG backend bridge invalid json",
                    {
                        "url": url,
                        "status_code": response.status_code,
                        "tenant_id": tenant_id,
                        "external_account_id": external_account_id,
                        "whatsapp_endpoint_id": whatsapp_endpoint_id,
                    },
                )
                raise WhatsAppBridgeError(status.HTTP_502_BAD_GATEWAY, "WhatsApp bridge returned invalid JSON") from exc
            if isinstance(response_body, dict):
                error_message = str(response_body.get("error") or response_body.get("detail") or error_message)
        else:
            response_body = response.text
            if response_body:
                error_message = str(response_body)

        status_code = response.status_code if response.status_code in {400, 401, 403, 404} else (
            status.HTTP_502_BAD_GATEWAY if response.status_code < 500 else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        print(
            "WA DEBUG backend bridge returned error",
            {
                "url": url,
                "status_code": response.status_code,
                "mapped_status_code": status_code,
                "tenant_id": tenant_id,
                "external_account_id": external_account_id,
                "whatsapp_endpoint_id": whatsapp_endpoint_id,
                "content_type": content_type,
            },
        )
        raise WhatsAppBridgeError(status_code, error_message, response_body)

    if content_type.startswith("application/json"):
        try:
            return response.json()
        except ValueError as exc:
            print(
                "WA DEBUG backend bridge success returned invalid json",
                {
                    "url": url,
                    "tenant_id": tenant_id,
                    "external_account_id": external_account_id,
                    "whatsapp_endpoint_id": whatsapp_endpoint_id,
                },
            )
            raise WhatsAppBridgeError(status.HTTP_502_BAD_GATEWAY, "WhatsApp bridge returned invalid JSON") from exc
    return response.text

