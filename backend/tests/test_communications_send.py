from datetime import datetime, timedelta, timezone

import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.user import User

SEND_FLOW_USER = User(id=3, email="send-flow-agent@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: SEND_FLOW_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def create_tenant(db_session, name="Tenant Outbound", booking_id="B-outbound", email=None):
    tenant = Tenant(name=name, booking_id=booking_id, email=email)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_email_send_rejects_one_of_our_own_mailboxes(user_client, db_session, monkeypatch):
    tenant = create_tenant(db_session, booking_id="B-email-own-mailbox")
    account = GmailAccount(email_address="crm@example.com", is_active=True)
    sibling_account = GmailAccount(email_address="info@shortstayinn.com", is_active=True)
    db_session.add_all([account, sibling_account])
    db_session.flush()

    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-own-mailbox", subject="Question")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id="msg-own-mailbox",
            direction="outbound",
            sender_email=account.email_address,
            recipient_email=sibling_account.email_address,
            subject="Re: Question",
            body="Forwarded internally",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, source="email_match"))
    db_session.commit()

    monkeypatch.setattr("app.api.communications._build_gmail_credentials", lambda account: object())
    monkeypatch.setattr(
        "app.api.communications.send_gmail_reply",
        lambda credentials, **kwargs: (_ for _ in ()).throw(AssertionError("send_gmail_reply should not be called")),
    )

    response = user_client.post(
        f"/api/communications/tenants/{tenant.id}/send",
        json={
            "channel": "email",
            "message": "Please reply to the tenant",
            "email_thread_id": conversation.id,
        },
    )

    assert response.status_code == 400
    assert "Cannot determine recipient email" in response.json()["detail"]
