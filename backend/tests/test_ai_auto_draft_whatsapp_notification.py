from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_approval_request import AiAutoDraftApprovalRequest
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.user import User
from app.services import ai_draft_notification_service
from app.services.ai_draft_notification_service import notify_admins_of_new_draft, notify_admins_of_redraft


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


def _patch_send(monkeypatch, result=None):
    sent_calls = []

    async def fake_send(to, message, external_account_id=None):
        sent_calls.append((to, message, external_account_id))
        return result

    monkeypatch.setattr(ai_draft_notification_service, "send_system_whatsapp_message", fake_send)
    return sent_calls


def test_learns_recipient_lid_identity_from_send_result(db_session, monkeypatch):
    # The bridge reports the recipient's @lid; storing it is what lets their reply - which
    # arrives from that @lid rather than their phone number - be attributed back to them.
    tenant = _create_tenant(db_session, booking_id="B-notify-draft-lid")
    _create_ai_settings(db_session, tenant)
    recipient = _create_user(db_session, email="draft-notify-lid@example.com")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant)

    _patch_send(monkeypatch, result={"whatsapp_identity_key": "155066153590862@lid"})

    notify_admins_of_new_draft(db_session, draft)

    db_session.refresh(recipient)
    assert recipient.whatsapp_identity_key == "155066153590862@lid"


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


def test_redraft_resets_existing_approval_request_and_resends_same_code(db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-notify-redraft-1")
    _create_ai_settings(db_session, tenant)
    recipient = _create_user(db_session, email="draft-redraft-user@example.com")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant, generated_text="Original text.")

    # First notification round, then the recipient responds - simulating the state right
    # before a REDO reply regenerates the draft in place.
    sent_calls = _patch_send(monkeypatch)
    notify_admins_of_new_draft(db_session, draft)
    request = db_session.query(AiAutoDraftApprovalRequest).one()

    draft.generated_text = "Regenerated, shorter text."
    sent_calls.clear()

    notify_admins_of_redraft(db_session, draft)

    assert len(sent_calls) == 1
    to, message, external_account_id = sent_calls[0]
    assert to == recipient.phone
    assert external_account_id == "edi-crm-whatsapp"
    assert "Regenerated, shorter text." in message
    assert f"YES-{draft.id}" in message
    assert f"NO-{draft.id}" in message
    assert f"REDO-{draft.id}" in message

    # Same row reused (no unique-constraint violation), reset back to unresponded.
    assert db_session.query(AiAutoDraftApprovalRequest).count() == 1
    db_session.refresh(request)
    assert request.responded_at is None
    assert request.response is None


def test_redraft_creates_row_for_newly_opted_in_recipient(db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-notify-redraft-2")
    _create_ai_settings(db_session, tenant)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant)

    sent_calls = _patch_send(monkeypatch)

    # No approval requests exist yet for this draft - notify_admins_of_redraft must still work.
    new_recipient = _create_user(db_session, email="draft-redraft-new@example.com")

    notify_admins_of_redraft(db_session, draft)

    assert len(sent_calls) == 1
    request = db_session.query(AiAutoDraftApprovalRequest).one()
    assert request.user_id == new_recipient.id
    assert request.responded_at is None


def test_redraft_does_not_gate_on_planner_mode_or_status(db_session, monkeypatch):
    # notify_admins_of_redraft is only called right after a successful regenerate, where the
    # tenant's planner_mode and the draft's status are already known-good, so unlike
    # notify_admins_of_new_draft it must not re-check them.
    tenant = _create_tenant(db_session, booking_id="B-notify-redraft-3")
    _create_ai_settings(db_session, tenant, planner_mode="auto-send")
    _create_user(db_session)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id="edi-crm-whatsapp"))
    db_session.commit()
    draft = _create_draft(db_session, tenant, status="needs_review")

    sent_calls = _patch_send(monkeypatch)

    notify_admins_of_redraft(db_session, draft)

    assert len(sent_calls) == 1
