from datetime import datetime, timedelta, timezone

import pytest

from app.models.admin_settings import AdminSettings
from app.models.notification import Notification
from app.models.notification_whatsapp_delivery import NotificationWhatsappDelivery
from app.models.notification_whatsapp_trigger import NotificationWhatsappTrigger
from app.models.tenant import Tenant
from app.models.user import User
from app.services import notification_whatsapp_service
from app.services.notification_whatsapp_service import (
    flush_due_notification_whatsapp_batch,
    register_notification_for_whatsapp,
)
from app.services.whatsapp_client import WhatsAppBridgeError


@pytest.fixture(autouse=True)
def _clean_notification_whatsapp_state(db_session):
    # Other test files exercise the WhatsApp/Gmail webhooks, which now register a trigger as a
    # side effect (register_notification_for_whatsapp). Since the trigger is a single global
    # row, a leftover row from an earlier test file (committed, and not rolled back due to the
    # shared SQLite test DB's known cross-test pollution) would otherwise bleed into these
    # tests' assertions about trigger state.
    db_session.query(NotificationWhatsappTrigger).delete()
    db_session.query(NotificationWhatsappDelivery).delete()
    # Same reasoning: mark any pre-existing Notification rows (created by unrelated tests'
    # webhook calls) as already dispatched so they don't inflate the "pending" batch this
    # file's tests build and assert against.
    db_session.query(Notification).filter(Notification.whatsapp_dispatched_at.is_(None)).update(
        {"whatsapp_dispatched_at": datetime.now(timezone.utc)}, synchronize_session=False
    )
    db_session.commit()
    yield


def _create_tenant(db_session, **overrides):
    defaults = dict(name="WA Notify Tenant", booking_id="B-wa-notify-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_notification(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        channel="whatsapp",
        direction="inbound",
        preview="Hello there",
        event_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    notification = Notification(**defaults)
    db_session.add(notification)
    db_session.commit()
    db_session.refresh(notification)
    return notification


def _create_user(db_session, **overrides):
    defaults = dict(
        email="wa-notify-user@example.com",
        password_hash="x",
        is_active=True,
        is_admin=False,
        phone="+31612345678",
        whatsapp_notifications_enabled=True,
    )
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_register_creates_and_debounces_single_trigger(db_session):
    tenant = _create_tenant(db_session)
    _create_notification(db_session, tenant)

    register_notification_for_whatsapp(db_session)
    db_session.commit()

    trigger = db_session.query(NotificationWhatsappTrigger).one()
    first_trigger_at = trigger.trigger_at

    register_notification_for_whatsapp(db_session)
    db_session.commit()

    triggers = db_session.query(NotificationWhatsappTrigger).all()
    assert len(triggers) == 1
    assert triggers[0].trigger_at >= first_trigger_at


def test_flush_noop_when_trigger_not_yet_due(db_session):
    tenant = _create_tenant(db_session)
    _create_notification(db_session, tenant)
    db_session.add(NotificationWhatsappTrigger(trigger_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
    db_session.commit()

    flush_due_notification_whatsapp_batch(db_session)

    assert db_session.query(NotificationWhatsappTrigger).count() == 1
    assert db_session.query(NotificationWhatsappDelivery).count() == 0


def test_flush_deletes_trigger_when_nothing_pending(db_session):
    db_session.add(NotificationWhatsappTrigger(trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db_session.commit()

    flush_due_notification_whatsapp_batch(db_session)

    assert db_session.query(NotificationWhatsappTrigger).count() == 0


def test_flush_sends_batched_message_to_opted_in_users_and_marks_dispatched(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    notification_a = _create_notification(db_session, tenant, preview="First message")
    notification_b = _create_notification(db_session, tenant, preview="Second message")
    recipient = _create_user(db_session, email="wa-notify-recipient@example.com")
    db_session.add(NotificationWhatsappTrigger(trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db_session.commit()

    sent_calls = []

    async def fake_send(to, message):
        sent_calls.append((to, message))

    monkeypatch.setattr(notification_whatsapp_service, "send_system_whatsapp_message", fake_send)

    flush_due_notification_whatsapp_batch(db_session)

    assert len(sent_calls) == 1
    to, message = sent_calls[0]
    assert to == recipient.phone
    assert "2 new notification(s)" in message
    assert "First message" in message
    assert "Second message" in message

    db_session.refresh(notification_a)
    db_session.refresh(notification_b)
    assert notification_a.whatsapp_dispatched_at is not None
    assert notification_b.whatsapp_dispatched_at is not None
    assert db_session.query(NotificationWhatsappTrigger).count() == 0

    delivery = db_session.query(NotificationWhatsappDelivery).one()
    assert delivery.user_id == recipient.id
    assert delivery.status == "sent"
    assert delivery.notification_count == 2


def test_flush_excludes_users_without_opt_in_phone_or_active(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_notification(db_session, tenant)
    _create_user(db_session, email="wa-notify-not-opted-in@example.com", whatsapp_notifications_enabled=False)
    _create_user(db_session, email="wa-notify-no-phone@example.com", phone=None)
    _create_user(db_session, email="wa-notify-inactive@example.com", is_active=False)
    db_session.add(NotificationWhatsappTrigger(trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db_session.commit()

    sent_calls = []

    async def fake_send(to, message):
        sent_calls.append((to, message))

    monkeypatch.setattr(notification_whatsapp_service, "send_system_whatsapp_message", fake_send)

    flush_due_notification_whatsapp_batch(db_session)

    assert sent_calls == []
    assert db_session.query(NotificationWhatsappDelivery).count() == 0


def test_flush_continues_after_one_recipient_failure_and_logs_delivery(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_notification(db_session, tenant)
    failing_user = _create_user(db_session, email="wa-notify-failing@example.com", phone="+31600000001")
    succeeding_user = _create_user(db_session, email="wa-notify-succeeding@example.com", phone="+31600000002")
    db_session.add(NotificationWhatsappTrigger(trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db_session.commit()

    sent_calls = []

    async def fake_send(to, message):
        if to == failing_user.phone:
            raise WhatsAppBridgeError(503, "bridge unavailable")
        sent_calls.append(to)

    monkeypatch.setattr(notification_whatsapp_service, "send_system_whatsapp_message", fake_send)

    flush_due_notification_whatsapp_batch(db_session)

    assert sent_calls == [succeeding_user.phone]
    deliveries = {d.user_id: d for d in db_session.query(NotificationWhatsappDelivery).all()}
    assert deliveries[failing_user.id].status == "failed"
    assert deliveries[failing_user.id].error_message
    assert deliveries[succeeding_user.id].status == "sent"


def test_debounce_seconds_falls_back_to_default_without_admin_settings(db_session):
    assert db_session.query(AdminSettings).first() is None
    before = datetime.now(timezone.utc)

    register_notification_for_whatsapp(db_session)
    db_session.commit()

    trigger = db_session.query(NotificationWhatsappTrigger).one()
    trigger_at = trigger.trigger_at if trigger.trigger_at.tzinfo else trigger.trigger_at.replace(tzinfo=timezone.utc)
    assert trigger_at >= before + timedelta(seconds=119)
    assert trigger_at <= before + timedelta(seconds=121)
