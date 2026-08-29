"""Regression tests for the Tier A stability fixes from the workspace audit.

Each test reproduces the prior failure mode:
  BE-1  get_current_user raised ValueError -> 500 on a non-numeric token subject.
  BE-2  create_tenant let a provisioning failure (LLM/DB) 500 the whole request.
  BE-3  concurrent inbound redelivery raced past the dedup SELECT and 500'd on the
        unique constraint, making the bridge redeliver in a loop.
  BE-6  a malformed JSON webhook body raised JSONDecodeError -> 500.
  BE-7  an unmapped exception fell through to Starlette's default error page.

BE-2/BE-3 exercise routes that legitimately commit (twice, or commit-then-rollback),
so they run against a real committing session rather than conftest's nested-transaction
`db_session` fixture (which cannot represent those semantics). Rows are cleaned up
explicitly to avoid polluting the shared SQLite test DB.
"""
import asyncio
import json
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.dependencies import get_current_admin_user, get_current_user, get_db
from app.core.security import ALGORITHM, SECRET_KEY
from app.main import _unhandled_exception_handler, app
from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint

TENANT_API_USER = SimpleNamespace(id=99, is_active=True, is_admin=True)

# Own engine to the same SQLite test DB conftest.prepare_database created the tables in; this
# session commits for real, mirroring the production get_db (a plain SessionLocal), unlike the
# nested-transaction db_session fixture.
_real_engine = create_engine("sqlite:///./backend_test.db", connect_args={"check_same_thread": False})
_RealSession = sessionmaker(autocommit=False, autoflush=False, bind=_real_engine)


@pytest.fixture()
def committing_client():
    def override_get_db():
        db = _RealSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = lambda: TENANT_API_USER
    app.dependency_overrides[get_current_user] = lambda: TENANT_API_USER
    with TestClient(app, headers={"X-Webhook-Secret": os.environ["CRM_WEBHOOK_SECRET"]}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# -- BE-1 ---------------------------------------------------------------------
def test_get_current_user_rejects_non_numeric_subject_with_401(db_session):
    token = jwt.encode({"sub": "not-an-int"}, SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(HTTPException) as excinfo:
        get_current_user(db=db_session, token=token)
    assert excinfo.value.status_code == 401


# -- BE-2 ---------------------------------------------------------------------
def test_create_tenant_survives_provisioning_failure(committing_client, monkeypatch):
    import app.api.tenants as tenants_module

    def boom(*_args, **_kwargs):
        raise RuntimeError("gemini timed out")

    # The inline initial-brain fill is the most likely real create-tenant 500 vector.
    monkeypatch.setattr(tenants_module.tenant_brain_service, "scan_tenant_history", boom)

    verify = _RealSession()
    try:
        response = committing_client.post("/api/tenants", json={"booking_id": "B-prov-fail", "name": "Prov Fail"})
        assert response.status_code == 201, response.text  # was a 500 before the fix
        tenant = verify.query(Tenant).filter(Tenant.booking_id == "B-prov-fail").first()
        assert tenant is not None  # core record persisted despite provisioning failure
    finally:
        verify.query(Tenant).filter(Tenant.booking_id == "B-prov-fail").delete()
        verify.commit()
        verify.close()


# -- BE-3 ---------------------------------------------------------------------
def test_inbound_duplicate_race_is_handled_not_500(committing_client, monkeypatch):
    import app.webhooks.whatsapp as whatsapp_module

    setup = _RealSession()
    try:
        tenant = Tenant(name="Race Tenant", booking_id="B-race", phone="+31600000000")
        setup.add(tenant)
        setup.flush()
        setup.add(
            TenantChannelEndpoint(
                tenant_id=tenant.id,
                channel_type="whatsapp",
                provider="whatsapp-service",
                external_account_id="edi-crm-whatsapp",
                external_chat_namespace="31612345678@c.us",
                is_active=True,
            )
        )
        setup.commit()
        tenant_id = tenant.id
    finally:
        setup.close()

    # Force both deliveries past the dedup SELECT so the second insert hits the
    # uq_communications_tenant_provider_message_id constraint -- the real race.
    monkeypatch.setattr(whatsapp_module, "_find_existing_inbound_whatsapp_communication", lambda *a, **k: None)

    payload = {
        "direction": "inbound",
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "sender": "+31612345678",
        "sender_normalized": "31612345678",
        "whatsapp_chat_id": "31612345678@c.us",
        "whatsapp_message_id": "msg-race-1",
        "timestamp": 1710000000,
        "message": "Racing inbound",
    }

    verify = _RealSession()
    try:
        first = committing_client.post("/webhooks/whatsapp", json=payload)
        second = committing_client.post("/webhooks/whatsapp", json=payload)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text  # was a 500 before the fix
        assert second.json()["message"] == "duplicate skipped"
        rows = verify.query(Communication).filter(Communication.provider_message_id == "msg-race-1").all()
        assert len(rows) == 1
    finally:
        verify.query(Communication).filter(Communication.tenant_id == tenant_id).delete()
        verify.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant_id).delete()
        verify.query(Tenant).filter(Tenant.id == tenant_id).delete()
        verify.commit()
        verify.close()


# -- BE-6 ---------------------------------------------------------------------
def test_malformed_json_webhook_body_returns_400(client):
    response = client.post(
        "/webhooks/whatsapp",
        content="{not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400  # was a 500 (JSONDecodeError) before the fix


# -- BE-7 ---------------------------------------------------------------------
def test_unhandled_exception_handler_returns_clean_500():
    fake_request = SimpleNamespace(method="GET", url=SimpleNamespace(path="/boom"))
    response = asyncio.run(_unhandled_exception_handler(fake_request, RuntimeError("kaboom")))
    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "Internal server error"}
