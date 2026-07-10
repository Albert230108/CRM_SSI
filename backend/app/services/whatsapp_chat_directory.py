import json
import os
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import status

from app.services.whatsapp_client import (
    WHATSAPP_API_KEY,
    WHATSAPP_SERVICE_URL,
    WHATSAPP_SERVICE_URL_MAP,
    WhatsAppBridgeError,
)

DEFAULT_PROVIDER = "whatsapp-service"


def list_whatsapp_accounts() -> list[dict[str, Any]]:
    """Return the WhatsApp service accounts available for manual chat linking.

    Sourced from WHATSAPP_SERVICE_ACCOUNTS (explicit list) when configured, falling back to
    the keys of WHATSAPP_SERVICE_URL_MAP (multi-account routing map), and finally to a single
    default account derived from WHATSAPP_SERVICE_URL for single-account deployments.
    """
    whatsapp_service_accounts = os.getenv("WHATSAPP_SERVICE_ACCOUNTS", "").strip()
    if whatsapp_service_accounts:
        try:
            parsed = json.loads(whatsapp_service_accounts)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            accounts: list[dict[str, Any]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                external_account_id = str(item.get("external_account_id") or "").strip()
                if not external_account_id:
                    continue
                accounts.append(
                    {
                        "external_account_id": external_account_id,
                        "provider": str(item.get("provider") or DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER,
                        "label": str(item.get("label") or external_account_id).strip() or external_account_id,
                    }
                )
            if accounts:
                return accounts

    if WHATSAPP_SERVICE_URL_MAP:
        try:
            mapping = json.loads(WHATSAPP_SERVICE_URL_MAP)
        except json.JSONDecodeError:
            mapping = None
        if isinstance(mapping, dict) and mapping:
            return [
                {"external_account_id": key, "provider": DEFAULT_PROVIDER, "label": key}
                for key in mapping
                if str(key).strip()
            ]

    if WHATSAPP_SERVICE_URL:
        default_account_id = os.getenv("WHATSAPP_DEFAULT_ACCOUNT_ID", "edi-crm-whatsapp").strip() or "edi-crm-whatsapp"
        return [{"external_account_id": default_account_id, "provider": DEFAULT_PROVIDER, "label": default_account_id}]

    return []


def _resolve_service_url(external_account_id: str) -> str | None:
    if WHATSAPP_SERVICE_URL_MAP:
        try:
            mapping = json.loads(WHATSAPP_SERVICE_URL_MAP)
            if isinstance(mapping, dict) and str(mapping.get(external_account_id, "")).strip():
                return str(mapping[external_account_id]).strip()
        except json.JSONDecodeError:
            pass
    return WHATSAPP_SERVICE_URL


async def fetch_whatsapp_chats(
    external_account_id: str,
    *,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch the live WhatsApp chat list for an account from its whatsapp-service instance."""
    service_url = _resolve_service_url(external_account_id)
    if not service_url:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge URL is not configured for this account")
    if not WHATSAPP_API_KEY:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge API key is not configured")

    url = urljoin(service_url.rstrip("/") + "/", "chats")
    params: dict[str, Any] = {"external_account_id": external_account_id, "limit": limit, "offset": offset}
    if search:
        params["search"] = search

    timeout = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers={"X-API-Key": WHATSAPP_API_KEY}, params=params)
    except httpx.TimeoutException as exc:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge request timed out") from exc
    except httpx.RequestError as exc:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge is unavailable") from exc

    if not response.is_success:
        error_message = "Failed to fetch WhatsApp chat list"
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("error"):
                error_message = str(body["error"])
        except ValueError:
            pass
        status_code = response.status_code if response.status_code in {400, 401, 403, 404} else (
            status.HTTP_502_BAD_GATEWAY if response.status_code < 500 else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise WhatsAppBridgeError(status_code, error_message)

    try:
        payload = response.json()
    except ValueError as exc:
        raise WhatsAppBridgeError(status.HTTP_502_BAD_GATEWAY, "WhatsApp bridge returned invalid JSON") from exc

    chats = payload.get("chats") if isinstance(payload, dict) else None
    return chats if isinstance(chats, list) else []


async def resync_whatsapp_chat(external_account_id: str, chat_id: str) -> dict[str, Any]:
    """Force a full-history resync of a single chat (used to backfill everything for a chat
    that was just manually linked, rather than waiting for the next scheduled sweep).

    Targeting a single chat_id makes backfillAllChats pull its *entire* history rather than the
    capped default, so this also fixes chats that were previously synced with only their most
    recent messages.
    """
    service_url = _resolve_service_url(external_account_id)
    if not service_url:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge URL is not configured for this account")
    if not WHATSAPP_API_KEY:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge API key is not configured")

    url = urljoin(service_url.rstrip("/") + "/", "admin/backfill")
    timeout = httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers={"X-API-Key": WHATSAPP_API_KEY}, json={"chatId": chat_id})
    except httpx.TimeoutException as exc:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge request timed out") from exc
    except httpx.RequestError as exc:
        raise WhatsAppBridgeError(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp bridge is unavailable") from exc

    if not response.is_success:
        error_message = "Failed to resync WhatsApp chat history"
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("error"):
                error_message = str(body["error"])
        except ValueError:
            pass
        status_code = response.status_code if response.status_code in {400, 401, 403, 404} else (
            status.HTTP_502_BAD_GATEWAY if response.status_code < 500 else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise WhatsAppBridgeError(status_code, error_message)

    try:
        return response.json()
    except ValueError as exc:
        raise WhatsAppBridgeError(status.HTTP_502_BAD_GATEWAY, "WhatsApp bridge returned invalid JSON") from exc
