import base64
from datetime import datetime, timedelta, timezone

from app.api.gmail_integration import _upsert_thread
from app.core.dependencies import get_current_user
from app.main import app
from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.notification import Notification
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.user import User

USER_ONE = User(id=101, email="notif-user-one@example.com", password_hash="x", is_active=True, is_admin=False)
USER_TWO = User(id=102, email="notif-user-two@example.com", password_hash="x", is_active=True, is_admin=False)


def create_tenant(db_session, name="Tenant A", booking_id="B-notif-1", email=None):
    tenant = Tenant(name=name, booking_id=booking_id, email=email)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_whatsapp_endpoint(db_session, tenant_id, external_account_id, provider="whatsapp-service"):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider=provider,
        external_account_id=external_account_id,
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def test_inbound_whatsapp_webhook_creates_notification(client, db_session):
    tenant = create_tenant(db_session, name="Jane Doe", booking_id="B-notif-2")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "tenant_id": tenant.id,
            "provider": "whatsapp-service",
            "external_account_id": "edi-crm-whatsapp",
            "sender": "+31 6 123 456 78",
            "sender_normalized": "31612345678",
            "whatsapp_chat_id": "31612345678@c.us",
            "whatsapp_message_id": "msg-notif-1",
            "message": "Hello there",
        },
    )
    assert response.status_code == 200

    saved = db_session.query(Communication).filter(Communication.tenant_id == tenant.id).one()
    assert saved.direction == "inbound"

    notification = db_session.query(Notification).filter(Notification.tenant_id == tenant.id).one()
    assert notification.tenant_name == "Jane Doe"
    assert notification.channel == "whatsapp"
    assert notification.direction == "inbound"
    assert notification.preview == "Hello there"


def test_outbound_whatsapp_webhook_does_not_create_notification(client, db_session):
    tenant = create_tenant(db_session, name="Jane Doe", booking_id="B-notif-3")
    create_whatsapp_endpoint(db_session, tenant.id, "edi-crm-whatsapp")

    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "outbound",
            "provider": "whatsapp-service",
            "tenant_id": tenant.id,
            "external_account_id": "edi-crm-whatsapp",
            "whatsapp_chat_id": "31612345678@c.us",
            "recipient": "+31 6 123 456 78",
            "message": "Outbound reply",
            "whatsapp_message_id": "msg-notif-outbound",
        },
    )
    assert response.status_code == 200
    assert db_session.query(Notification).filter(Notification.tenant_id == tenant.id).count() == 0


def test_inbound_email_linked_to_tenant_creates_notification(db_session):
    tenant = create_tenant(db_session, name="John Smith", booking_id="B-notif-4", email="john@example.com")
    account = GmailAccount(email_address="crm@example.com", refresh_token_encrypted="x")
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    thread = {
        "id": "thread-1",
        "messages": [
            {
                "id": "msg-1",
                "internalDate": "1700000000000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "John Smith <john@example.com>"},
                        {"name": "To", "value": "crm@example.com"},
                        {"name": "Subject", "value": "Question about booking"},
                    ],
                    "mimeType": "text/plain",
                    "body": {"data": b64("Hi, I have a question.")},
                },
            }
        ],
    }

    conversation = _upsert_thread(db_session, account, thread)
    db_session.commit()

    assert conversation is not None
    assert conversation.tenant_id == tenant.id
    saved_message = db_session.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id).one()
    assert saved_message.direction == "inbound"

    notification = db_session.query(Notification).filter(Notification.tenant_id == tenant.id).one()
    assert notification.tenant_name == "John Smith"
    assert notification.channel == "email"
    assert notification.direction == "inbound"
    assert notification.preview == "Hi, I have a question."


def test_inbound_email_notification_uses_message_time_not_import_time(db_session):
    """Regression test: a Gmail sync that finally picks up a message hours/days after it
    actually arrived (delayed history poll, expired watch, manual "sync all") must not make
    the notification look like it just came in. event_at must reflect the message's own
    internalDate, independent of when this row happens to be inserted."""
    tenant = create_tenant(db_session, name="Eva Toth-Nagy", booking_id="B-notif-7", email="eva@example.com")
    account = GmailAccount(email_address="crm@example.com", refresh_token_encrypted="x")
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    two_days_ago_ms = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp() * 1000)
    thread = {
        "id": "thread-stale",
        "messages": [
            {
                "id": "msg-stale",
                "internalDate": str(two_days_ago_ms),
                "labelIds": ["INBOX"],
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Eva Toth-Nagy <eva@example.com>"},
                        {"name": "To", "value": "crm@example.com"},
                        {"name": "Subject", "value": "Delayed message"},
                    ],
                    "mimeType": "text/plain",
                    "body": {"data": b64("Arrived 2 days ago, synced just now.")},
                },
            }
        ],
    }

    before_import = datetime.now(timezone.utc)
    conversation = _upsert_thread(db_session, account, thread)
    db_session.commit()

    assert conversation is not None
    notification = db_session.query(Notification).filter(Notification.tenant_id == tenant.id).one()
    event_at = notification.event_at.replace(tzinfo=timezone.utc) if notification.event_at.tzinfo is None else notification.event_at
    created_at = notification.created_at.replace(tzinfo=timezone.utc) if notification.created_at.tzinfo is None else notification.created_at
    assert event_at < before_import - timedelta(hours=1)
    assert created_at >= before_import - timedelta(seconds=1)


def test_inbound_email_without_matching_tenant_does_not_create_notification(db_session):
    account = GmailAccount(email_address="crm-2@example.com", refresh_token_encrypted="x")
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)

    thread = {
        "id": "thread-2",
        "messages": [
            {
                "id": "msg-2",
                "internalDate": "1700000000000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "stranger@example.com"},
                        {"name": "To", "value": "crm-2@example.com"},
                    ],
                    "mimeType": "text/plain",
                    "body": {"data": b64("Unrelated message")},
                },
            }
        ],
    }

    conversation = _upsert_thread(db_session, account, thread)
    db_session.commit()

    assert conversation is not None
    assert conversation.tenant_id is None
    assert db_session.query(Notification).count() == 0


def test_list_notifications_respects_unread_only_and_limit(non_admin_client, db_session):
    tenant = create_tenant(db_session, name="Tenant List", booking_id="B-notif-5")
    for i in range(3):
        db_session.add(Notification(tenant_id=tenant.id, tenant_name=tenant.name, channel="whatsapp", direction="inbound", preview=f"msg {i}"))
    db_session.commit()

    all_response = non_admin_client.get("/api/notifications", params={"limit": 10})
    assert all_response.status_code == 200
    payload = all_response.json()
    assert len(payload) == 3
    assert all(item["is_read"] is False for item in payload)

    limited_response = non_admin_client.get("/api/notifications", params={"limit": 2})
    assert len(limited_response.json()) == 2

    first_id = all_response.json()[0]["id"]
    mark_response = non_admin_client.post(f"/api/notifications/{first_id}/mark-read")
    assert mark_response.status_code == 200

    unread_only_response = non_admin_client.get("/api/notifications", params={"unread_only": True, "limit": 10})
    unread_payload = unread_only_response.json()
    assert len(unread_payload) == 2
    assert all(item["id"] != first_id for item in unread_payload)


def test_mark_read_and_mark_all_read_are_per_user(db_session):
    tenant = create_tenant(db_session, name="Tenant Read", booking_id="B-notif-6")
    notification_a = Notification(tenant_id=tenant.id, tenant_name=tenant.name, channel="whatsapp", direction="inbound", preview="a")
    notification_b = Notification(tenant_id=tenant.id, tenant_name=tenant.name, channel="email", direction="inbound", preview="b")
    db_session.add_all([notification_a, notification_b])
    db_session.commit()
    db_session.refresh(notification_a)
    db_session.refresh(notification_b)

    def override_db():
        try:
            yield db_session
        finally:
            pass

    from app.core.dependencies import get_db
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: USER_TWO
    try:
        with TestClient(app) as user_two_client:
            mark_response = user_two_client.post(f"/api/notifications/{notification_a.id}/mark-read")
            assert mark_response.status_code == 200
            assert mark_response.json()["is_read"] is True

            unread_response = user_two_client.get("/api/notifications/unread-count")
            assert unread_response.json()["count"] == 1

        app.dependency_overrides[get_current_user] = lambda: USER_ONE
        with TestClient(app) as user_one_client:
            unread_response = user_one_client.get("/api/notifications/unread-count")
            assert unread_response.json()["count"] == 2

            mark_all_response = user_one_client.post("/api/notifications/mark-all-read")
            assert mark_all_response.json()["marked"] == 2

            unread_response = user_one_client.get("/api/notifications/unread-count")
            assert unread_response.json()["count"] == 0

        app.dependency_overrides[get_current_user] = lambda: USER_TWO
        with TestClient(app) as user_two_client:
            unread_response = user_two_client.get("/api/notifications/unread-count")
            assert unread_response.json()["count"] == 1
    finally:
        app.dependency_overrides.clear()
