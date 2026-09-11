"""
Regression/unit tests for the delegated-auth OneDrive token exchange in onedrive_service.py.

get_access_token_and_drive_id() replaces the old app-only client-credentials flow with a
refresh-token exchange against Microsoft's consumers (personal account) endpoint. Microsoft's
v2 token endpoint rotates refresh tokens on each use, so every successful call must re-persist
whatever refresh token comes back - skipping that breaks the next call. All Graph/token-endpoint
calls are mocked; nothing here talks to a real network.
"""

from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.models.admin_settings import AdminSettings
from app.services import onedrive_service

TEST_KEY = Fernet.generate_key().decode("utf-8")


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, data=None):
        return self._response


def _patch_token_response(monkeypatch, status_code: int, payload: dict):
    def _factory(*args, **kwargs):
        return _FakeAsyncClient(_FakeResponse(status_code, payload))

    monkeypatch.setattr(onedrive_service.httpx, "AsyncClient", _factory)


def _configured_settings(db_session, monkeypatch, refresh_token: str = "old-refresh-token") -> AdminSettings:
    monkeypatch.setenv("ONEDRIVE_TOKEN_ENCRYPTION_KEY", TEST_KEY)
    encrypted = onedrive_service.encrypt_refresh_token(refresh_token)
    settings = AdminSettings(
        onedrive_refresh_token_encrypted=encrypted,
        onedrive_drive_id="drive-123",
    )
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)
    return settings


@pytest.mark.asyncio
async def test_raises_503_when_unconfigured(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await onedrive_service.get_access_token_and_drive_id(db_session)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_successful_refresh_persists_rotated_token(db_session, monkeypatch):
    settings = _configured_settings(db_session, monkeypatch)
    _patch_token_response(
        monkeypatch,
        200,
        {"access_token": "new-access-token", "refresh_token": "rotated-refresh-token"},
    )

    access_token, drive_id = await onedrive_service.get_access_token_and_drive_id(db_session)

    assert access_token == "new-access-token"
    assert drive_id == "drive-123"
    db_session.refresh(settings)
    assert onedrive_service.decrypt_refresh_token(settings.onedrive_refresh_token_encrypted) == "rotated-refresh-token"
    assert settings.onedrive_token_updated_at is not None


@pytest.mark.asyncio
async def test_no_spurious_write_when_microsoft_does_not_rotate(db_session, monkeypatch):
    settings = _configured_settings(db_session, monkeypatch)
    original_encrypted = settings.onedrive_refresh_token_encrypted
    _patch_token_response(monkeypatch, 200, {"access_token": "new-access-token"})

    access_token, _drive_id = await onedrive_service.get_access_token_and_drive_id(db_session)

    assert access_token == "new-access-token"
    db_session.refresh(settings)
    assert settings.onedrive_refresh_token_encrypted == original_encrypted
    assert settings.onedrive_token_updated_at is None


@pytest.mark.asyncio
async def test_502_on_graph_error_leaves_old_token_untouched(db_session, monkeypatch):
    settings = _configured_settings(db_session, monkeypatch)
    original_encrypted = settings.onedrive_refresh_token_encrypted
    _patch_token_response(monkeypatch, 400, {"error": "invalid_grant"})

    with pytest.raises(HTTPException) as exc_info:
        await onedrive_service.get_access_token_and_drive_id(db_session)

    assert exc_info.value.status_code == 502
    db_session.refresh(settings)
    assert settings.onedrive_refresh_token_encrypted == original_encrypted
    assert settings.onedrive_token_updated_at is None


@pytest.mark.asyncio
async def test_missing_encryption_key_at_rotation_time_logs_and_skips_persist(db_session, monkeypatch, caplog):
    settings = _configured_settings(db_session, monkeypatch)
    original_encrypted = settings.onedrive_refresh_token_encrypted
    # Simulate the key going missing only at rotation (persist) time, after the stored token
    # was already read successfully - bypass the read-side decrypt so this test isolates the
    # persist-time failure mode rather than also tripping the "unconfigured" 503 path.
    monkeypatch.setattr(onedrive_service, "decrypt_refresh_token", lambda encrypted: "old-refresh-token")
    monkeypatch.delenv("ONEDRIVE_TOKEN_ENCRYPTION_KEY", raising=False)
    _patch_token_response(
        monkeypatch,
        200,
        {"access_token": "new-access-token", "refresh_token": "rotated-refresh-token"},
    )

    with caplog.at_level("ERROR"):
        access_token, drive_id = await onedrive_service.get_access_token_and_drive_id(db_session)

    assert access_token == "new-access-token"
    assert drive_id == "drive-123"
    assert any("ONEDRIVE_TOKEN_ENCRYPTION_KEY" in record.message for record in caplog.records)
    db_session.refresh(settings)
    assert settings.onedrive_refresh_token_encrypted == original_encrypted
    assert settings.onedrive_token_updated_at is None
