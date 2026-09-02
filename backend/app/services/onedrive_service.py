"""
Microsoft Graph helpers for writing quotation PDFs into the same OneDrive
Tenants/ folder tree the CRM already reads from (see tenants.py's
get_tenant_onedrive_files). App-only client-credentials auth, driven by the
MS_GRAPH_* env vars - the quotation-manager service never holds these; it hands
generated PDFs to the CRM, which uploads them here.

Folder layout matches the CRM's existing convention exactly so quotation PDFs
land in the folder the file-list endpoint shows:
    /01. Rentals/02. Short-Stay Inn/Tenants/{year}/{booking}_{first}_{last}
"""

from __future__ import annotations

import logging
import os
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
TENANTS_ROOT = "/01. Rentals/02. Short-Stay Inn/Tenants"


async def get_graph_access_token() -> str:
    tenant_id = os.getenv("MS_GRAPH_TENANT_ID")
    client_id = os.getenv("MS_GRAPH_CLIENT_ID")
    client_secret = os.getenv("MS_GRAPH_CLIENT_SECRET")
    if not tenant_id or not client_id or not client_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Microsoft Graph is not configured")

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
                "scope": "https://graph.microsoft.com/.default",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to authenticate with Microsoft Graph")
    token = response.json().get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Microsoft Graph access token missing")
    return str(token)


def _drive_id() -> str:
    drive_id = os.getenv("MS_GRAPH_DRIVE_ID")
    if not drive_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Microsoft Graph drive is not configured")
    return drive_id


def tenant_folder_path(booking_id: str, first_name: str, last_name: str, year: int) -> str:
    # Same naming as tenants.py _build_one_drive_folder_path so both point at the
    # identical folder: booking_first_last with spaces -> underscores.
    folder_name = f"{booking_id}_{first_name}_{last_name}".replace(" ", "_")
    return f"{TENANTS_ROOT}/{year}/{folder_name}"


def _item_url(drive_id: str, path: str, suffix: str) -> str:
    # /drives/{id}/root:{url-encoded path}:{suffix}
    return f"{GRAPH_ROOT}/drives/{drive_id}/root:{quote(path, safe='/')}:{suffix}"


async def list_child_names(access_token: str, folder_path: str) -> list[str]:
    drive_id = _drive_id()
    url = _item_url(drive_id, folder_path, "/children")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code == 404:
        return []
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to list Microsoft Graph folder")
    values = response.json().get("value") or []
    return [item.get("name") for item in values if item.get("name")]


async def ensure_folder(access_token: str, folder_path: str) -> None:
    """Create each missing folder segment under the drive root so an upload into a
    not-yet-existing tenant folder succeeds. Idempotent: existing folders (409)
    are treated as success."""
    drive_id = _drive_id()
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


async def upload_pdf(access_token: str, folder_path: str, filename: str, content: bytes) -> dict:
    drive_id = _drive_id()
    await ensure_folder(access_token, folder_path)
    url = _item_url(drive_id, f"{folder_path}/{filename}", "/content")
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/pdf"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.put(url, headers=headers, content=content)
    if response.status_code >= 400:
        logger.warning("Graph upload failed filename=%s status=%s", filename, response.status_code)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to upload PDF to OneDrive")
    body = response.json()
    return {"name": body.get("name", filename), "web_url": body.get("webUrl"), "id": body.get("id")}
