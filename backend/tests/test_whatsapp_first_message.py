import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User
from app.services.whatsapp_client import WhatsAppBridgeError

FIRST_MESSAGE_USER = User(id=4, email="first-message-agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    # The shared `client` fixture only overrides get_current_admin_user; routes guarded by
    # get_current_user (like this endpoint) need this override too.
    app.dependency_overrides[get_current_user] = lambda: FIRST_MESSAGE_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def create_tenant(db_session, name="New Tenant", booking_id="B-first-1", phone="+31600000001"):
    tenant = Tenant(name=name, booking_id=booking_id, phone=phone)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_whatsapp_endpoint(db_session, tenant_id, external_account_id, chat_id=None, provider="whatsapp-service"):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider=provider,
        external_account_id=external_account_id,
        external_chat_namespace=chat_id,
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


def _stub_accounts(monkeypatch, account_id="edi-crm-whatsapp"):
    monkeypatch.setattr(
        "app.api.communications.list_whatsapp_accounts",
        lambda: [{"external_account_id": account_id, "provider": "whatsapp-service", "label": "EDI CRM WhatsApp"}],
    )


def test_first_message_happy_path_sends_and_auto_links(user_client, db_session, monkeypatch):
    tenant = create_tenant(db_session)
    _stub_accounts(monkeypatch)

    async def fake_send_whatsapp_message(payload):
        assert payload["require_registered_recipient"] is True
        assert payload["whatsapp_endpoint_id"] is None
        return {
            "whatsapp_message_id": "msg-first-1",
            "whatsapp_chat_id": "31612345678@c.us",
        }

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send-first-message",
        json={
            "to": "+31612345678",
            "message": "Hi, welcome!",
            "external_account_id": "edi-crm-whatsapp",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == tenant.id
    assert body["channel"] == "whatsapp"
    assert body["direction"] == "outbound"

    endpoint = (
        db_session.query(TenantChannelEndpoint)
        .filter(TenantChannelEndpoint.tenant_id == tenant.id, TenantChannelEndpoint.channel_type == "whatsapp")
        .first()
    )
    assert endpoint is not None
    assert endpoint.is_active is True
    assert endpoint.source == "auto_first_send"
    assert endpoint.external_chat_namespace == "31612345678@c.us"
    assert endpoint.linked_by_user_id == FIRST_MESSAGE_USER.id


def test_first_message_allowed_alongside_existing_endpoint_adds_second_chat(user_client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-first-2")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp", chat_id="31600000000@c.us")
    _stub_accounts(monkeypatch)

    async def fake_send_whatsapp_message(payload):
        return {"whatsapp_message_id": "msg-first-2", "whatsapp_chat_id": "31612345678@c.us"}

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send-first-message",
        json={"to": "+31612345678", "message": "Hi", "external_account_id": "edi-crm-whatsapp"},
    )

    assert response.status_code == 201

    active_endpoints = (
        db_session.query(TenantChannelEndpoint)
        .filter(TenantChannelEndpoint.tenant_id == tenant.id, TenantChannelEndpoint.is_active.is_(True))
        .all()
    )
    chat_ids = {endpoint.external_chat_namespace for endpoint in active_endpoints}
    assert chat_ids == {"31600000000@c.us", "31612345678@c.us"}


def test_first_message_chat_conflict_still_sends_but_skips_auto_link(user_client, db_session, monkeypatch):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-first-conflict-a")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-first-conflict-b")
    create_whatsapp_endpoint(db_session, tenant_a.id, "edi-crm-whatsapp", chat_id="31699999999@c.us")
    _stub_accounts(monkeypatch)

    async def fake_send_whatsapp_message(payload):
        return {"whatsapp_message_id": "msg-conflict-1", "whatsapp_chat_id": "31699999999@c.us"}

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = user_client.post(
        f"/api/communications/tenants/{tenant_b.id}/send-first-message",
        json={"to": "+31699999999", "message": "Hi", "external_account_id": "edi-crm-whatsapp"},
    )

    assert response.status_code == 201

    active_endpoints_for_b = (
        db_session.query(TenantChannelEndpoint)
        .filter(
            TenantChannelEndpoint.tenant_id == tenant_b.id,
            TenantChannelEndpoint.channel_type == "whatsapp",
            TenantChannelEndpoint.is_active.is_(True),
        )
        .count()
    )
    assert active_endpoints_for_b == 0

    # Tenant A's original link is untouched.
    endpoint_a = (
        db_session.query(TenantChannelEndpoint)
        .filter(TenantChannelEndpoint.tenant_id == tenant_a.id, TenantChannelEndpoint.is_active.is_(True))
        .first()
    )
    assert endpoint_a is not None
    assert endpoint_a.external_chat_namespace == "31699999999@c.us"


def test_first_message_unregistered_number_returns_422(user_client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-first-3")
    _stub_accounts(monkeypatch)

    async def fake_send_whatsapp_message(payload):
        raise WhatsAppBridgeError(422, "Recipient is not a registered WhatsApp user")

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send-first-message",
        json={"to": "+31600000009", "message": "Hi", "external_account_id": "edi-crm-whatsapp"},
    )

    assert response.status_code == 422
    assert db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant.id).count() == 0


def test_first_message_rejects_unconnected_account(user_client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-first-4")
    _stub_accounts(monkeypatch, account_id="some-other-account")

    async def fake_send_whatsapp_message(payload):
        raise AssertionError("send_whatsapp_message should not be called for an unconnected account")

    monkeypatch.setattr("app.api.communications.send_whatsapp_message", fake_send_whatsapp_message)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send-first-message",
        json={"to": "+31612345678", "message": "Hi", "external_account_id": "edi-crm-whatsapp"},
    )

    assert response.status_code == 400


def test_first_message_rejects_empty_message_without_attachments(user_client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-first-5")
    _stub_accounts(monkeypatch)

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send-first-message",
        json={"to": "+31612345678", "message": "   ", "external_account_id": "edi-crm-whatsapp"},
    )

    assert response.status_code == 400


def test_first_message_rejects_unknown_tenant(user_client, monkeypatch):
    _stub_accounts(monkeypatch)

    response = user_client.post(
        "/api/communications/tenants/999999/send-first-message",
        json={"to": "+31612345678", "message": "Hi", "external_account_id": "edi-crm-whatsapp"},
    )

    assert response.status_code == 404
