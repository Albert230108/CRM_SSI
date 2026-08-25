from datetime import date, timedelta

from app.models.action_item import ActionItem
from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_approval_request import AiAutoDraftApprovalRequest
from app.models.memory_suggestion import KIND_ACTION_ITEM_DELETE, KIND_ACTION_ITEM_MODIFY, MemorySuggestion
from app.models.tenant import Tenant
from app.models.user import User
from app.webhooks import whatsapp as whatsapp_webhook_module

NOTIFICATION_ACCOUNT_ID = "edi-crm-whatsapp"


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Digest Tenant", booking_id="B-digest-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_user(db_session, **overrides):
    defaults = dict(
        email="digest-user@example.com",
        password_hash="x",
        full_name="Alice Staff",
        is_active=True,
        is_admin=False,
        phone="+31611112222",
        whatsapp_notifications_enabled=True,
    )
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_action_item(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        title="Follow up with guest",
        description="Call back about breakfast",
        due_date=date.today(),
        status="open",
        source="manual",
    )
    defaults.update(overrides)
    item = ActionItem(**defaults)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _create_modify_suggestion(db_session, tenant, item, **overrides):
    defaults = dict(
        kind=KIND_ACTION_ITEM_MODIFY,
        tenant_id=tenant.id,
        target_id=item.id,
        proposed_value={
            "title": "Follow up with guest ASAP",
            "due_date": (date.today() + timedelta(days=2)).isoformat(),
            "description": "Call before checkout",
        },
        status="pending",
    )
    defaults.update(overrides)
    suggestion = MemorySuggestion(**defaults)
    db_session.add(suggestion)
    db_session.commit()
    db_session.refresh(suggestion)
    return suggestion


def _create_delete_suggestion(db_session, tenant, item, **overrides):
    defaults = dict(
        kind=KIND_ACTION_ITEM_DELETE,
        tenant_id=tenant.id,
        target_id=item.id,
        proposed_value={},
        status="pending",
    )
    defaults.update(overrides)
    suggestion = MemorySuggestion(**defaults)
    db_session.add(suggestion)
    db_session.commit()
    db_session.refresh(suggestion)
    return suggestion


def _create_draft(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        channel="whatsapp",
        generated_text="Hi there, thanks for reaching out!",
        status="pending",
    )
    defaults.update(overrides)
    draft = AiAutoDraft(**defaults)
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)
    return draft


def _create_approval_request(db_session, draft, user):
    request = AiAutoDraftApprovalRequest(
        ai_auto_draft_id=draft.id,
        user_id=user.id,
        phone=user.phone,
        external_account_id=NOTIFICATION_ACCOUNT_ID,
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)
    return request


def _patch_confirmation_send(monkeypatch):
    sent_calls = []

    async def fake_send(to, message, external_account_id=None):
        sent_calls.append((to, message, external_account_id))

    monkeypatch.setattr(whatsapp_webhook_module, "send_system_whatsapp_message", fake_send)
    return sent_calls


def _post_reply(client, *, sender, message, external_account_id=NOTIFICATION_ACCOUNT_ID, chat_id=None):
    payload = {
        "direction": "inbound",
        "provider": "whatsapp-service",
        "external_account_id": external_account_id,
        "sender": sender,
        "whatsapp_message_id": f"msg-{sender}-{message}",
        "message": message,
    }
    if chat_id is not None:
        payload["whatsapp_chat_id"] = chat_id
    return client.post("/webhooks/whatsapp", json=payload)


def test_actions_today_upcoming_and_help_commands(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    other_tenant = _create_tenant(db_session, name="Second Tenant", booking_id="B-digest-2")
    _create_user(db_session)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()

    _create_action_item(db_session, tenant, title="Overdue item", due_date=date.today() - timedelta(days=1))
    _create_action_item(db_session, other_tenant, title="Due today", due_date=date.today())
    _create_action_item(db_session, tenant, title="Upcoming item", due_date=date.today() + timedelta(days=3))
    _create_action_item(db_session, tenant, title="Too far out", due_date=date.today() + timedelta(days=10))
    _create_action_item(db_session, tenant, title="Completed item", due_date=date.today(), status="done")

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender="+31611112222", message="actions")
    assert response.status_code == 200
    assert "Overdue item" in sent_calls[0][1]
    assert "Due today" in sent_calls[0][1]
    assert "Upcoming item" not in sent_calls[0][1]
    assert "Too far out" not in sent_calls[0][1]
    assert "Completed item" not in sent_calls[0][1]

    sent_calls.clear()
    response = _post_reply(client, sender="+31611112222", message="actions today")
    assert response.status_code == 200
    assert "Overdue item" in sent_calls[0][1]
    assert "Due today" in sent_calls[0][1]
    assert "Upcoming item" not in sent_calls[0][1]

    sent_calls.clear()
    response = _post_reply(client, sender="+31611112222", message="actions upcoming")
    assert response.status_code == 200
    assert "Upcoming item" in sent_calls[0][1]
    assert "Overdue item" not in sent_calls[0][1]
    assert "Due today" not in sent_calls[0][1]

    sent_calls.clear()
    response = _post_reply(client, sender="+31611112222", message="help")
    assert response.status_code == 200
    assert "AI draft approvals" in sent_calls[0][1]
    assert "Action items" in sent_calls[0][1]


def test_actions_pending_lists_and_applies_suggestions(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-digest-pending")
    user = _create_user(db_session, email="pending-user@example.com")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()

    item = _create_action_item(db_session, tenant, title="Follow up with guest", due_date=date.today())
    modify = _create_modify_suggestion(db_session, tenant, item)
    delete_item = _create_action_item(db_session, tenant, title="Remove duplicate reminder", due_date=date.today() + timedelta(days=1))
    delete = _create_delete_suggestion(db_session, tenant, delete_item)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message="actions pending")
    assert response.status_code == 200
    message = sent_calls[0][1]
    assert f"#{modify.id}" in message
    assert f"#{delete.id}" in message
    assert "Follow up with guest ASAP" in message
    assert "Reply YES-" in message

    sent_calls.clear()
    response = _post_reply(client, sender=user.phone, message=f"YES-{modify.id}")
    assert response.status_code == 200
    assert "Approved action-item suggestion" in sent_calls[0][1]
    db_session.refresh(modify)
    db_session.refresh(item)
    assert modify.status == "approved"
    assert item.title == "Follow up with guest ASAP"

    sent_calls.clear()
    response = _post_reply(client, sender=user.phone, message=f"NO-{delete.id}")
    assert response.status_code == 200
    assert "Rejected action-item suggestion" in sent_calls[0][1]
    db_session.refresh(delete)
    assert delete.status == "rejected"


def test_plain_code_collision_requires_disambiguation(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-digest-collision")
    user = _create_user(db_session, email="collision-user@example.com")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()

    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)
    item = _create_action_item(db_session, tenant)
    suggestion = MemorySuggestion(
        id=draft.id,
        kind=KIND_ACTION_ITEM_MODIFY,
        tenant_id=tenant.id,
        target_id=item.id,
        proposed_value={"title": "Collision update"},
        status="pending",
    )
    db_session.add(suggestion)
    db_session.commit()
    db_session.refresh(suggestion)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message=f"YES-{draft.id}")
    assert response.status_code == 200
    assert "matches both" in sent_calls[0][1]
    assert f"DRAFT-YES-{draft.id}" in sent_calls[0][1]
    assert f"ACTION-YES-{draft.id}" in sent_calls[0][1]

    db_session.refresh(draft)
    db_session.refresh(suggestion)
    assert draft.status == "pending"
    assert suggestion.status == "pending"


def test_commands_and_codes_ignore_wrong_account_or_non_opted_in_sender(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-digest-gating")
    _create_action_item(db_session, tenant)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender="+31619990000", message="actions pending")
    assert response.status_code == 200
    assert response.json()["message"] == "inbound unresolved"
    assert sent_calls == []

    response = _post_reply(client, sender="+31619990000", message="YES-9999", external_account_id="wrong-account")
    assert response.status_code == 200
    assert response.json()["message"] == "inbound unresolved"
    assert sent_calls == []
