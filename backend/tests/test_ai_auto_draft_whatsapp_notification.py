from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_approval_request import AiAutoDraftApprovalRequest
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.user import User
from app.services import ai_draft_notification_service
from app.services.ai_draft_notification_service import notify_admins_of_new_draft


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Notify Draft Tenant", booking_id="B-notify-draft-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_ai_settings(db_session, tenant, planner_mode="auto-draft"):
    settings = TenantAiSettings(tenant_id=tenant.id, planner_mode=planner_mode)
    db_session.add(settings)
    db_session.commit()
    return settings


def _create_user(db_session, **overrides):
    defaults = dict(
        email="draft-notify-user@example.com",
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


def _patch_send(monkeypatch):
    sent_calls = []

    async def fake_send(to, message, external_account_id=None):
        sent_calls.append((to, message, external_account_id))

    monkeypatch.setattr(ai_draft_notification_service, "send_system_whatsapp_message", fake_send)
    return sent_calls


def test_notifies_opted_in_recipient_for_auto_draft_pending_draft(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    recipient = _create_user(db_session)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant)

    sent_calls = _patch_send(monkeypatch)

    notify_admins_of_new_draft(db_session, draft)

    assert len(sent_calls) == 1
    to, message, external_account_id = sent_calls[0]
    assert to == recipient.phone
    assert external_account_id == "edi-crm-whatsapp"
    assert tenant.name in message
    assert f"YES-{draft.id}" in message
    assert f"NO-{draft.id}" in message

    request = db_session.query(AiAutoDraftApprovalRequest).one()
    assert request.ai_auto_draft_id == draft.id
    assert request.user_id == recipient.id
    assert request.phone == recipient.phone
    assert request.responded_at is None


def test_needs_review_draft_gets_warning_prefix(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    _create_user(db_session)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant, status="needs_review")

    sent_calls = _patch_send(monkeypatch)

    notify_admins_of_new_draft(db_session, draft)

    assert len(sent_calls) == 1
    assert "Needs review" in sent_calls[0][1]


def test_skips_notification_for_auto_send_mode(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant, planner_mode="auto-send")
    _create_user(db_session)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant)

    sent_calls = _patch_send(monkeypatch)

    notify_admins_of_new_draft(db_session, draft)

    assert sent_calls == []
    assert db_session.query(AiAutoDraftApprovalRequest).count() == 0


def test_skips_notification_for_manual_and_off_modes(db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-notify-draft-2")
    _create_ai_settings(db_session, tenant, planner_mode="manual")
    _create_user(db_session)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant)

    sent_calls = _patch_send(monkeypatch)

    notify_admins_of_new_draft(db_session, draft)

    assert sent_calls == []


def test_skips_when_no_notification_account_configured(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    _create_user(db_session)
    draft = _create_draft(db_session, tenant)

    sent_calls = _patch_send(monkeypatch)

    notify_admins_of_new_draft(db_session, draft)

    assert sent_calls == []
    assert db_session.query(AiAutoDraftApprovalRequest).count() == 0


def test_skips_when_no_opted_in_recipients(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant)

    sent_calls = _patch_send(monkeypatch)

    notify_admins_of_new_draft(db_session, draft)

    assert sent_calls == []


def test_skips_when_draft_already_resolved(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _create_ai_settings(db_session, tenant)
    _create_user(db_session)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant, status="sent")

    sent_calls = _patch_send(monkeypatch)

    notify_admins_of_new_draft(db_session, draft)

    assert sent_calls == []
