from datetime import datetime, timedelta, timezone

from app.core.dependencies import get_current_user
from app.main import app
from app.models.device_token import DeviceToken
from app.models.notification import Notification
from app.models.notification_push_trigger import NotificationPushTrigger
from app.models.user import User
from app.services import push_notification_service
from app.services.push_notification_service import (
    flush_due_notification_push_batch,
    register_notification_for_push,
)


def _make_user(db_session, user_id=501, email="dev-user@example.com"):
    user = User(id=user_id, email=email, password_hash="x", is_active=True, is_admin=False)
    db_session.add(user)
    db_session.commit()
    return user


def _auth_as(user):
    # Device endpoints depend on get_current_user; the `client` fixture only overrides the admin
    # dependency, so each test pins the acting user here. Cleared by the fixture teardown.
    app.dependency_overrides[get_current_user] = lambda: user


def _make_notification(db_session, tenant_name="Jane", channel="whatsapp", preview="hello"):
    notification = Notification(
        tenant_id=None,
        tenant_name=tenant_name,
        channel=channel,
        direction="inbound",
        preview=preview,
        event_at=datetime.now(timezone.utc),
    )
    db_session.add(notification)
    db_session.commit()
    return notification


def _due_trigger(db_session):
    db_session.add(
        NotificationPushTrigger(trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    db_session.commit()


# --- register / unregister endpoints ---


def test_register_device_creates_row(client, db_session):
    user = _make_user(db_session)
    _auth_as(user)

    resp = client.post(
        "/api/devices/register",
        json={"token": "ExponentPushToken[abc]", "platform": "android"},
    )

    assert resp.status_code == 200
    assert resp.json()["token"] == "ExponentPushToken[abc]"
    rows = db_session.query(DeviceToken).all()
    assert len(rows) == 1
    assert rows[0].user_id == user.id
    assert rows[0].platform == "android"


def test_register_device_is_idempotent_upsert(client, db_session):
    user = _make_user(db_session)
    _auth_as(user)

    client.post("/api/devices/register", json={"token": "tok-1", "platform": "android"})
    client.post("/api/devices/register", json={"token": "tok-1", "platform": "ios"})

    rows = db_session.query(DeviceToken).filter(DeviceToken.token == "tok-1").all()
    assert len(rows) == 1
    assert rows[0].platform == "ios"


def test_register_reassigns_token_to_new_user(client, db_session):
    first = _make_user(db_session, user_id=511, email="a@example.com")
    second = _make_user(db_session, user_id=512, email="b@example.com")

    _auth_as(first)
    client.post("/api/devices/register", json={"token": "shared"})
    _auth_as(second)
    client.post("/api/devices/register", json={"token": "shared"})

    rows = db_session.query(DeviceToken).filter(DeviceToken.token == "shared").all()
    assert len(rows) == 1
    assert rows[0].user_id == second.id


def test_unregister_removes_own_token(client, db_session):
    user = _make_user(db_session)
    _auth_as(user)
    client.post("/api/devices/register", json={"token": "tok-x"})

    resp = client.post("/api/devices/unregister", json={"token": "tok-x"})

    assert resp.status_code == 204
    assert db_session.query(DeviceToken).count() == 0


def test_register_empty_token_rejected(client, db_session):
    user = _make_user(db_session)
    _auth_as(user)

    resp = client.post("/api/devices/register", json={"token": "   "})

    assert resp.status_code == 400


# --- debounce trigger + batched flush ---


def test_register_notification_for_push_sets_single_trigger(db_session):
    # Each ingestion request commits its own transaction, so a later notification's register
    # call sees the existing row and resets it rather than stacking a second trigger.
    assert db_session.query(NotificationPushTrigger).count() == 0
    register_notification_for_push(db_session)
    db_session.commit()
    first_trigger_at = db_session.query(NotificationPushTrigger).one().trigger_at

    register_notification_for_push(db_session)
    db_session.commit()

    triggers = db_session.query(NotificationPushTrigger).all()
    assert len(triggers) == 1
    assert triggers[0].trigger_at >= first_trigger_at


def test_flush_sends_push_and_marks_dispatched(db_session, monkeypatch):
    user = _make_user(db_session, user_id=601)
    db_session.add(DeviceToken(user_id=user.id, token="ExponentPushToken[ok]", platform="android"))
    notification = _make_notification(db_session)
    _due_trigger(db_session)

    sent: dict = {}

    def fake_send(messages):
        sent["messages"] = messages
        return [{"status": "ok", "id": "ticket-1"}]

    monkeypatch.setattr(push_notification_service, "_send_expo_batch", fake_send)

    flush_due_notification_push_batch(db_session)

    assert sent["messages"][0]["to"] == "ExponentPushToken[ok]"
    db_session.refresh(notification)
    assert notification.push_dispatched_at is not None
    assert db_session.query(NotificationPushTrigger).count() == 0


def test_flush_prunes_device_not_registered(db_session, monkeypatch):
    user = _make_user(db_session, user_id=602)
    db_session.add(DeviceToken(user_id=user.id, token="dead-token"))
    _make_notification(db_session)
    _due_trigger(db_session)

    monkeypatch.setattr(
        push_notification_service,
        "_send_expo_batch",
        lambda messages: [{"status": "error", "details": {"error": "DeviceNotRegistered"}}],
    )

    flush_due_notification_push_batch(db_session)

    assert db_session.query(DeviceToken).filter(DeviceToken.token == "dead-token").count() == 0


def test_flush_logs_non_device_registered_error(db_session, monkeypatch, caplog):
    # Regression: the prod push outage returned InvalidCredentials (FCM key missing on Expo) for
    # every device, but the flush only handled DeviceNotRegistered - so the failure was swallowed
    # silently and everything was marked dispatched as if delivered. A non-DeviceNotRegistered
    # error must be logged, the (still-valid) token must NOT be pruned, and dispatch still advances.
    user = _make_user(db_session, user_id=603)
    db_session.add(DeviceToken(user_id=user.id, token="ExponentPushToken[live]", platform="android"))
    notification = _make_notification(db_session)
    _due_trigger(db_session)

    monkeypatch.setattr(
        push_notification_service,
        "_send_expo_batch",
        lambda messages: [
            {
                "status": "error",
                "message": "Unable to retrieve the FCM server key for the recipient's app.",
                "details": {"error": "InvalidCredentials", "fault": "developer"},
            }
        ],
    )

    with caplog.at_level("ERROR", logger="app.services.push_notification_service"):
        flush_due_notification_push_batch(db_session)

    # Token is a real, still-registered device: keep it, unlike DeviceNotRegistered.
    assert (
        db_session.query(DeviceToken).filter(DeviceToken.token == "ExponentPushToken[live]").count()
        == 1
    )
    # Dispatch still advances (don't-retry-forever invariant is preserved).
    db_session.refresh(notification)
    assert notification.push_dispatched_at is not None
    # The failure is now visible, and the raw token is not leaked into the log.
    assert "InvalidCredentials" in caplog.text
    assert "ExponentPushToken[live]" not in caplog.text


def test_flush_no_due_trigger_is_noop(db_session, monkeypatch):
    _make_notification(db_session)
    calls = {"n": 0}

    def fake_send(messages):
        calls["n"] += 1
        return []

    monkeypatch.setattr(push_notification_service, "_send_expo_batch", fake_send)

    flush_due_notification_push_batch(db_session)

    assert calls["n"] == 0
