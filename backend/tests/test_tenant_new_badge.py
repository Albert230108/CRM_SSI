from datetime import datetime, timedelta, timezone

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.user import User

NEW_BADGE_USER = User(id=7, email="new-badge-agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: NEW_BADGE_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def create_tenant(db_session, name="New Tenant", booking_id="B-new", email=None):
    tenant = Tenant(name=name, booking_id=booking_id, email=email)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_new_tenant_defaults_to_is_new_true(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-new-default")

    assert tenant.is_new is True

    response = user_client.get(f"/api/tenants/{tenant.id}")
    assert response.status_code == 200
    assert response.json()["is_new"] is True


def test_dismiss_new_endpoint_clears_flag(user_client, db_session):
    tenant = create_tenant(db_session, booking_id="B-new-dismiss")

    response = user_client.patch(f"/api/tenants/{tenant.id}/dismiss-new")

    assert response.status_code == 200
    assert response.json() == {"is_new": False}

    db_session.refresh(tenant)
    assert tenant.is_new is False


def test_dismiss_new_endpoint_404_for_missing_tenant(user_client):
    response = user_client.patch("/api/tenants/999999/dismiss-new")
    assert response.status_code == 404


def test_email_send_clears_is_new(user_client, db_session, monkeypatch):
    # Regression: before this change, sending the first message left the "New" badge stuck on.
    tenant = create_tenant(db_session, booking_id="B-new-email-send")
    assert tenant.is_new is True

    account = GmailAccount(email_address="crm@example.com", is_active=True)
    db_session.add(account)
    db_session.flush()

    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-new-badge", subject="Question")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id="msg-new-badge-inbound",
            direction="inbound",
            sender_email="guest@example.com",
            recipient_email=account.email_address,
            subject="Question",
            body="Hello",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            raw_payload={"gmail": {"payload": {"headers": [{"name": "Message-ID", "value": "<msg-new-badge-inbound@mail>"}]}}},
        )
    )
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, source="email_match"))
    db_session.commit()

    monkeypatch.setattr("app.api.communications._build_gmail_credentials", lambda account: object())
    monkeypatch.setattr("app.api.communications.send_gmail_reply", lambda credentials, **kwargs: {"id": "gmail-new-badge-outbound"})

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "email",
            "message": "Welcome!",
            "email_thread_id": conversation.id,
        },
    )

    assert response.status_code == 201

    db_session.refresh(tenant)
    assert tenant.is_new is False
