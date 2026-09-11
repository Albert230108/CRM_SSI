"""
One-time bootstrap for delegated (sign-in) Microsoft Graph auth to the OneDrive
account that quotation PDFs get uploaded to.

App-only client-credentials auth (the old MS_GRAPH_* env vars) cannot reach a
personal Microsoft account's OneDrive at all, so this uses the OAuth
device-code flow instead: no redirect URI, no client secret, just an
interactive sign-in on any device.

This is a manual, interactive, one-off tool - it talks to live Microsoft
endpoints by design and is intentionally excluded from automated tests.

Usage (run from backend/):
    python scripts/onedrive_device_auth.py
    python scripts/onedrive_device_auth.py --print-token   # for environments without DB access
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from app.database import SessionLocal
from app.models.admin_settings import AdminSettings
from app.services.onedrive_service import DEVICE_AUTH_CLIENT_ID, encrypt_refresh_token

AUTHORITY = "https://login.microsoftonline.com/consumers"
DEVICE_CODE_URL = f"{AUTHORITY}/oauth2/v2.0/devicecode"
TOKEN_URL = f"{AUTHORITY}/oauth2/v2.0/token"
# .All because the target folder is a shared item the signed-in personal account doesn't
# own outright - plain Files.ReadWrite is unreliable for reading/writing shared items.
SCOPE = "Files.ReadWrite.All offline_access"

# The folder tree quotation PDFs must land in is owned by this drive - Alberto confirmed
# (2026-09-02, reconfirmed today) this is the personal account to sign into. No code can
# determine this on its own; the printed drive id below must be checked against it by hand.
EXPECTED_DRIVE_ID = "2d8437e948c68053"


def _request_device_code(client: httpx.Client) -> dict:
    response = client.post(DEVICE_CODE_URL, data={"client_id": DEVICE_AUTH_CLIENT_ID, "scope": SCOPE})
    response.raise_for_status()
    return response.json()


def _poll_for_token(client: httpx.Client, device_code: str, interval: int, expires_in: int) -> dict:
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": DEVICE_AUTH_CLIENT_ID,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
            },
        )
        payload = response.json()
        error = payload.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            raise RuntimeError(f"Device code flow failed: {error} - {payload.get('error_description')}")
        return payload
    raise RuntimeError("Timed out waiting for sign-in")


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time OneDrive delegated-auth bootstrap (device-code sign-in)")
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print the raw refresh token. Only use this when running somewhere without DB access; "
        "never share or log the printed value.",
    )
    args = parser.parse_args()

    if not args.print_token and not os.getenv("ONEDRIVE_TOKEN_ENCRYPTION_KEY"):
        print(
            "ONEDRIVE_TOKEN_ENCRYPTION_KEY is not set. Set it before persisting a token, "
            "or pass --print-token to view the token without persisting.",
            file=sys.stderr,
        )
        return 1

    with httpx.Client(timeout=30) as client:
        device_code_payload = _request_device_code(client)
        print(f"Open {device_code_payload['verification_uri']} on any device and enter code: {device_code_payload['user_code']}")
        print("Waiting for sign-in...")
        token_payload = _poll_for_token(
            client,
            device_code_payload["device_code"],
            device_code_payload.get("interval", 5),
            device_code_payload.get("expires_in", 900),
        )

        refresh_token = token_payload.get("refresh_token")
        access_token = token_payload.get("access_token")
        if not refresh_token or not access_token:
            print("Sign-in did not return the expected tokens.", file=sys.stderr)
            return 1

        drive_response = client.get(
            "https://graph.microsoft.com/v1.0/me/drive",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        drive_response.raise_for_status()
        drive = drive_response.json()

    drive_id = drive.get("id")
    owner = (drive.get("owner") or {}).get("user") or {}
    owner_label = owner.get("displayName") or owner.get("email") or "unknown"

    print(f"Signed-in drive id: {drive_id}")
    print(f"Drive owner: {owner_label}")
    print(f"Expected drive id: {EXPECTED_DRIVE_ID}")
    if drive_id != EXPECTED_DRIVE_ID:
        print(
            "Drive id does NOT match the expected OneDrive account. Stopping without persisting "
            "anything - sign in with the correct personal account and re-run.",
            file=sys.stderr,
        )
        return 1

    if args.print_token:
        print(f"Refresh token: {refresh_token}")

    answer = input("Drive id confirmed. Persist this refresh token to AdminSettings? [y/N] ").strip().lower()
    if answer != "y":
        print("Not persisting. Re-run and confirm 'y' to save.")
        return 0

    encrypted = encrypt_refresh_token(refresh_token)
    if encrypted is None:
        print("ONEDRIVE_TOKEN_ENCRYPTION_KEY is not set; cannot encrypt the refresh token for storage.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        settings = db.query(AdminSettings).first()
        if settings is None:
            settings = AdminSettings()
            db.add(settings)
        settings.onedrive_refresh_token_encrypted = encrypted
        settings.onedrive_drive_id = drive_id
        settings.onedrive_account_label = owner_label
        settings.onedrive_token_updated_at = datetime.now(timezone.utc)
        db.commit()
        print("Persisted OneDrive delegated auth to AdminSettings.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
