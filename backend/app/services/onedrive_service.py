"""
Microsoft Graph helpers for writing quotation PDFs into the same OneDrive
Tenants/ folder tree the CRM already reads from (see tenants.py's
get_tenant_onedrive_files).

Delegated (sign-in) auth, not app-only client-credentials: the target folder
tree lives on a personal Microsoft OneDrive account, which app-only auth
cannot access at all. A refresh token is obtained once via the interactive
device-code bootstrap script (backend/scripts/onedrive_device_auth.py) and
stored encrypted in AdminSettings; every call here exchanges it for a fresh
access token and re-persists whatever refresh token Microsoft returns, since
the v2 endpoint rotates refresh tokens on each use.

Folder layout matches the CRM's existing convention exactly so quotation PDFs
land in the folder the file-list endpoint shows:
    /01. Rentals/02. Short-Stay Inn/Tenants/{year}/{booking}_{first}_{last}
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.admin_settings import AdminSettings

logger = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
TENANTS_ROOT = "/01. Rentals/02. Short-Stay Inn/Tenants"

# Microsoft's own OneDrive desktop app public client id, reused so no separate Azure app
# registration is needed. Works with the device-code flow against the consumers (personal
# account) authority, no client secret required.
DEVICE_AUTH_CLIENT_ID = "d50ca740-c83f-4d1b-b616-12c519384f0c"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"


def _cipher() -> Fernet | None:
    key = os.getenv("ONEDRIVE_TOKEN_ENCRYPTION_KEY")
    if not key:
        return None
    return Fernet(key.encode("utf-8"))


def encrypt_refresh_token(refresh_token: str) -> str | None:
    cipher = _cipher()
    if cipher is None:
        return None
    return cipher.encrypt(refresh_token.encode("utf-8")).decode("utf-8")


def decrypt_refresh_token(encrypted_refresh_token: str | None) -> str | None:
    if not encrypted_refresh_token:
        return None
    cipher = _cipher()
    if cipher is None:
        return None
    try:
        return cipher.decrypt(encrypted_refresh_token.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


async def get_access_token_and_drive_id(db: Session) -> tuple[str, str]:
    """Exchange the stored refresh token for a fresh access token, re-persisting the
    (possibly rotated) refresh token Microsoft returns. Raises 503 if OneDrive hasn't
    been configured yet (no bootstrap run), 502 on a Graph/token-endpoint failure -
    in both cases callers (e.g. quotation-manager's generate_pdf) fall back to saving
    the PDF locally instead."""
    settings = db.query(AdminSettings).first()
    if settings is None or not settings.onedrive_refresh_token_encrypted or not settings.onedrive_drive_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive is not configured")

    refresh_token = decrypt_refresh_token(settings.onedrive_refresh_token_encrypted)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OneDrive is not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": DEVICE_AUTH_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "Files.ReadWrite.All offline_access",
            },
        )
    if response.status_code >= 400:
        logger.warning("OneDrive token refresh failed status=%s", response.status_code)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to authenticate with Microsoft Graph")

    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Microsoft Graph access token missing")

    rotated_refresh_token = payload.get("refresh_token")
    if rotated_refresh_token:
        encrypted = encrypt_refresh_token(rotated_refresh_token)
        if encrypted is None:
            logger.error("ONEDRIVE_TOKEN_ENCRYPTION_KEY is not set; skipping refresh-token rotation persist")
        else:
            settings.onedrive_refresh_token_encrypted = encrypted
            settings.onedrive_token_updated_at = datetime.now(timezone.utc)
            db.commit()

    return str(access_token), str(settings.onedrive_drive_id)


def tenant_folder_path(booking_id: str, first_name: str, last_name: str, year: int) -> str:
    # Same naming as tenants.py _build_one_drive_folder_path so both point at the
    # identical folder: booking_first_last with spaces -> underscores.
    folder_name = f"{booking_id}_{first_name}_{last_name}".replace(" ", "_")
    return f"{TENANTS_ROOT}/{year}/{folder_name}"


def _item_url(drive_id: str, path: str, suffix: str) -> str:
    # /drives/{id}/root:{url-encoded path}:{suffix}
    return f"{GRAPH_ROOT}/drives/{drive_id}/root:{quote(path, safe='/')}:{suffix}"


async def list_child_names(access_token: str, drive_id: str, folder_path: str) -> list[str]:
    url = _item_url(drive_id, folder_path, "/children")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code == 404:
        return []
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to list Microsoft Graph folder")
    values = response.json().get("value") or []
    return [item.get("name") for item in values if item.get("name")]


async def ensure_folder(access_token: str, drive_id: str, folder_path: str) -> None:
    """Create each missing folder segment under the drive root so an upload into a
    not-yet-existing tenant folder succeeds. Idempotent: existing folders (409)
    are treated as success."""
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    segments = [seg for seg in folder_path.strip("/").split("/") if seg]
    parent = ""
    async with httpx.AsyncClient(timeout=30) as client:
        for segment in segments:
            if parent:
                children_url = _item_url(drive_id, parent, "/children")
            else:
                children_url = f"{GRAPH_ROOT}/drives/{drive_id}/root/children"
            body = {"name": segment, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
            response = await client.post(children_url, headers=headers, json=body)
            # 201 created, 409 already exists - both fine. Anything else is a real error.
            if response.status_code not in (201, 409):
                logger.warning("Graph ensure_folder failed segment=%s status=%s", segment, response.status_code)
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to create OneDrive folder")
            parent = f"{parent}/{segment}" if parent else segment


async def upload_pdf(access_token: str, drive_id: str, folder_path: str, filename: str, content: bytes) -> dict:
    await ensure_folder(access_token, drive_id, folder_path)
    url = _item_url(drive_id, f"{folder_path}/{filename}", "/content")
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/pdf"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.put(url, headers=headers, content=content)
    if response.status_code >= 400:
        logger.warning("Graph upload failed filename=%s status=%s", filename, response.status_code)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to upload PDF to OneDrive")
    body = response.json()
    return {"name": body.get("name", filename), "web_url": body.get("webUrl"), "id": body.get("id")}
