from datetime import datetime, timezone

from app.models.admin_settings import AdminSettings
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_approval_request import AiAutoDraftApprovalRequest
from app.models.communication import Communication
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services import ai_auto_draft_service, ai_draft_notification_service
from app.webhooks import whatsapp as whatsapp_webhook_module

NOTIFICATION_ACCOUNT_ID = "edi-crm-whatsapp"


def _create_tenant(db_session, **overrides):
    defaults = dict(name="Approval Webhook Tenant", booking_id="B-approval-webhook-1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_user(db_session, **overrides):
    defaults = dict(
        email="approval-webhook-user@example.com",
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


def _create_approval_request(db_session, draft, user, **overrides):
    defaults = dict(ai_auto_draft_id=draft.id, user_id=user.id, phone=user.phone, external_account_id=NOTIFICATION_ACCOUNT_ID)
    defaults.update(overrides)
    request = AiAutoDraftApprovalRequest(**defaults)
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


def test_yes_reply_sends_draft_and_confirms(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    user = _create_user(db_session)
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)

    def fake_send_scheduled_draft(db, draft_arg):
        draft_arg.status = "sent"
        return True

    monkeypatch.setattr(ai_auto_draft_service, "send_scheduled_draft", fake_send_scheduled_draft)
    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message=f"YES-{draft.id}")

    assert response.status_code == 200
    assert response.json()["message"] == "staff draft approval handled"
    assert len(sent_calls) == 1
    to, confirmation, _ = sent_calls[0]
    assert to == user.phone
    assert "Sent to" in confirmation

    db_session.refresh(draft)
    assert draft.status == "sent"
    request = db_session.query(AiAutoDraftApprovalRequest).one()
    assert request.response == "YES"
    assert request.responded_at is not None
    assert db_session.query(Communication).count() == 0


def test_no_reply_dismisses_draft(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-2")
    user = _create_user(db_session, email="approval-webhook-user-2@example.com", phone="+31611113333")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message=f"no-{draft.id}")

    assert response.status_code == 200
    assert "dismissed" in sent_calls[0][1].lower()

    db_session.refresh(draft)
    assert draft.status == "dismissed"
    assert draft.scheduled_send_at is None


def test_second_admin_reply_after_resolution_reports_who_answered(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-3")
    first_user = _create_user(db_session, email="approval-webhook-first@example.com", phone="+31611114444", full_name="Alice Staff")
    second_user = _create_user(db_session, email="approval-webhook-second@example.com", phone="+31611115555", full_name="Bob Staff")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant, status="sent")
    _create_approval_request(
        db_session, draft, first_user, responded_at=datetime.now(timezone.utc), response="YES"
    )
    _create_approval_request(db_session, draft, second_user)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=second_user.phone, message=f"NO-{draft.id}")

    assert response.status_code == 200
    confirmation = sent_calls[0][1]
    assert "Alice Staff" in confirmation
    assert "YES" in confirmation

    second_request = (
        db_session.query(AiAutoDraftApprovalRequest).filter(AiAutoDraftApprovalRequest.user_id == second_user.id).one()
    )
    assert second_request.responded_at is None


def test_lid_reply_is_matched_by_stored_identity_key(client, db_session, monkeypatch):
    # Regression: a staff member on an @lid-addressed WhatsApp account replies from that @lid,
    # never from their phone number, so phone matching alone silently dropped their approval.
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-lid")
    user = _create_user(
        db_session,
        email="approval-webhook-lid@example.com",
        phone="+31628882727",
        whatsapp_identity_key="155066153590862@lid",
    )
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)

    def fake_send_scheduled_draft(db, draft_arg):
        draft_arg.status = "sent"
        return True

    monkeypatch.setattr(ai_auto_draft_service, "send_scheduled_draft", fake_send_scheduled_draft)
    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(
        client,
        sender="155066153590862@lid",
        message=f"YES-{draft.id}",
        chat_id="155066153590862@lid",
    )

    assert response.status_code == 200
    assert response.json()["message"] == "staff draft approval handled"

    # The confirmation goes to the stored phone, not back to the unroutable @lid sender id.
    assert sent_calls[0][0] == user.phone
    assert "Sent to" in sent_calls[0][1]

    db_session.refresh(draft)
    assert draft.status == "sent"


def test_lid_reply_matches_when_canonical_identity_is_the_crm_number(client, db_session, monkeypatch):
    # Regression for the real production failure: for an inbound message from an @lid sender
    # the canonical identity resolves to the CRM's *own* number (it falls back to the
    # recipient's phone when the sender has none), so matching must use the raw sender/chat id.
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-lid-canonical")
    user = _create_user(
        db_session,
        email="approval-webhook-lid-canonical@example.com",
        phone="+31628882727",
        whatsapp_identity_key="155066153590862@lid",
    )
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)

    def fake_send_scheduled_draft(db, draft_arg):
        draft_arg.status = "sent"
        return True

    monkeypatch.setattr(ai_auto_draft_service, "send_scheduled_draft", fake_send_scheduled_draft)
    sent_calls = _patch_confirmation_send(monkeypatch)

    # recipient_normalized is what drags the canonical identity onto the CRM's own number.
    response = client.post(
        "/webhooks/whatsapp",
        json={
            "direction": "inbound",
            "provider": "whatsapp-service",
            "external_account_id": NOTIFICATION_ACCOUNT_ID,
            "sender": "155066153590862@lid",
            "whatsapp_chat_id": "155066153590862@lid",
            "recipient": "31538200946@c.us",
            "recipient_normalized": "31538200946",
            "whatsapp_message_id": "msg-lid-canonical",
            "message": f"YES-{draft.id}",
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "staff draft approval handled"
    assert sent_calls[0][0] == user.phone
    assert "Sent to" in sent_calls[0][1]

    db_session.refresh(draft)
    assert draft.status == "sent"


def test_bare_yes_never_sends_single_outstanding_draft(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-bare")
    user = _create_user(db_session, email="approval-webhook-bare@example.com", phone="+31611118888")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)

    def fail_if_called(db, draft_arg):
        raise AssertionError("bare yes must not send a draft")

    monkeypatch.setattr(ai_auto_draft_service, "send_scheduled_draft", fail_if_called)
    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message="yes")

    assert response.status_code == 200
    assert sent_calls[0][0] == user.phone
    assert f"YES-{draft.id}" in sent_calls[0][1]
    assert "Please reply" in sent_calls[0][1]
    db_session.refresh(draft)
    assert draft.status == "pending"


def test_bare_yes_with_multiple_outstanding_asks_for_disambiguation(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-ambig")
    user = _create_user(db_session, email="approval-webhook-ambig@example.com", phone="+31611119999")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    first = _create_draft(db_session, tenant)
    second = _create_draft(db_session, tenant)
    _create_approval_request(db_session, first, user)
    _create_approval_request(db_session, second, user)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message="yes")

    assert response.status_code == 200
    confirmation = sent_calls[0][1]
    assert "ambiguous" in confirmation
    assert f"YES-{first.id}" in confirmation
    assert f"YES-{second.id}" in confirmation

    db_session.refresh(first)
    db_session.refresh(second)
    assert first.status == "pending"
    assert second.status == "pending"


def test_bare_yes_with_nothing_outstanding_reports_back(client, db_session, monkeypatch):
    _create_user(db_session, email="approval-webhook-none@example.com", phone="+31611110000")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender="+31611110000", message="yes")

    assert response.status_code == 200
    assert "no AI drafts waiting" in sent_calls[0][1]


def test_superseded_draft_reply_explains_status(client, db_session, monkeypatch):
    # Drafts are superseded when a newer inbound message arrives, which is easy to hit in the
    # gap between the notification and the reply - the admin must be told, not ignored.
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-superseded")
    user = _create_user(db_session, email="approval-webhook-superseded@example.com", phone="+31611112121")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant, status="superseded")
    _create_approval_request(db_session, draft, user)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message=f"YES-{draft.id}")

    assert response.status_code == 200
    assert "no longer pending" in sent_calls[0][1]
    assert "superseded" in sent_calls[0][1]


def test_reply_from_non_admin_phone_falls_through_to_normal_routing(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-4")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender="+31699998888", message=f"YES-{draft.id}")

    assert response.status_code == 200
    assert response.json()["message"] == "inbound unresolved"
    assert sent_calls == []


def test_reply_on_wrong_external_account_falls_through(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-5")
    user = _create_user(db_session, email="approval-webhook-wrong-account@example.com", phone="+31611116666")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message=f"YES-{draft.id}", external_account_id="ssi-crm-whatsapp")

    assert response.status_code == 200
    assert response.json()["message"] == "inbound unresolved"
    assert sent_calls == []

    db_session.refresh(draft)
    assert draft.status == "pending"


def test_redo_reply_regenerates_draft_in_place_and_rebroadcasts(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-redo-1")
    user = _create_user(db_session, email="approval-webhook-redo-1@example.com", phone="+31611120001")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    approval_request = _create_approval_request(db_session, draft, user)

    regenerate_calls = []

    def fake_regenerate(db, draft_arg, instructions):
        regenerate_calls.append((draft_arg.id, instructions))
        draft_arg.generated_text = "Shorter reply, deposit mentioned."
        draft_arg.status = "pending"
        return draft_arg

    monkeypatch.setattr(ai_auto_draft_service, "regenerate_draft_via_planner", fake_regenerate)

    broadcast_calls = []

    async def fake_broadcast_send(to, message, external_account_id=None):
        broadcast_calls.append((to, message, external_account_id))
        return {}

    monkeypatch.setattr(ai_draft_notification_service, "send_system_whatsapp_message", fake_broadcast_send)
    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message=f"REDO-{draft.id} make it shorter and mention the deposit")

    assert response.status_code == 200
    assert response.json()["message"] == "staff draft approval handled"
    # No what:/why: labels in the message - the whole free-text instructions become "What".
    assert regenerate_calls == [(draft.id, "What: make it shorter and mention the deposit")]

    log_entry = db_session.query(RedoRequestLog).filter(RedoRequestLog.ai_auto_draft_id == draft.id).one()
    assert log_entry.channel == "whatsapp"
    assert log_entry.what == "make it shorter and mention the deposit"
    assert log_entry.why is None
    assert log_entry.requested_by_user_id == user.id

    # The webhook's own confirmation send is skipped entirely for a successful redo - the
    # acknowledgement and the redone-draft broadcast (both below) already cover it, and the
    # acknowledgement must be the first thing sent so it lands before the regenerated draft.
    assert sent_calls == []
    assert len(broadcast_calls) == 2
    ack_to, ack_message, ack_account = broadcast_calls[0]
    assert ack_to == user.phone
    assert ack_account == NOTIFICATION_ACCOUNT_ID
    assert "Redoing" in ack_message

    to, message, external_account_id = broadcast_calls[1]
    assert to == user.phone
    assert external_account_id == NOTIFICATION_ACCOUNT_ID
    assert "Shorter reply, deposit mentioned." in message
    assert f"YES-{draft.id}" in message
    assert f"NO-{draft.id}" in message
    assert f"REDO-{draft.id}" in message

    db_session.refresh(draft)
    assert draft.status == "pending"
    assert draft.generated_text == "Shorter reply, deposit mentioned."

    db_session.refresh(approval_request)
    assert approval_request.responded_at is None
    assert approval_request.response is None


def test_redo_reply_extracts_what_and_why_regardless_of_order(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-redo-order")
    user = _create_user(db_session, email="approval-webhook-redo-order@example.com", phone="+31611120099")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()

    async def fake_broadcast_send(to, message, external_account_id=None):
        return {}

    monkeypatch.setattr(ai_draft_notification_service, "send_system_whatsapp_message", fake_broadcast_send)
    _patch_confirmation_send(monkeypatch)

    cases = [
        ("make it shorter why: they already asked yesterday", "What: make it shorter\nWhy: they already asked yesterday"),
        ("why: they already asked yesterday what: make it shorter", "What: make it shorter\nWhy: they already asked yesterday"),
        ("WHAT: make it shorter", "What: make it shorter"),
    ]
    for suffix, expected_instructions in cases:
        draft = _create_draft(db_session, tenant)
        _create_approval_request(db_session, draft, user)
        regenerate_calls = []

        def fake_regenerate(db, draft_arg, instructions, _calls=regenerate_calls):
            _calls.append(instructions)
            draft_arg.generated_text = "Revised."
            draft_arg.status = "pending"
            return draft_arg

        monkeypatch.setattr(ai_auto_draft_service, "regenerate_draft_via_planner", fake_regenerate)

        response = _post_reply(client, sender=user.phone, message=f"REDO-{draft.id} {suffix}")
        assert response.status_code == 200
        assert regenerate_calls == [expected_instructions]


def test_redo_reply_without_instructions_asks_for_them(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-redo-2")
    user = _create_user(db_session, email="approval-webhook-redo-2@example.com", phone="+31611120002")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)

    regenerate_calls = []
    monkeypatch.setattr(
        ai_auto_draft_service,
        "regenerate_draft_via_planner",
        lambda db, draft_arg, instructions: regenerate_calls.append(instructions),
    )
    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message=f"REDO-{draft.id}")

    assert response.status_code == 200
    assert "include what to change" in sent_calls[0][1]
    assert regenerate_calls == []

    db_session.refresh(draft)
    assert draft.status == "pending"


def test_redo_reply_on_already_resolved_draft_reports_status(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-redo-3")
    user = _create_user(db_session, email="approval-webhook-redo-3@example.com", phone="+31611120003")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant, status="sent")
    _create_approval_request(
        db_session, draft, user, responded_at=datetime.now(timezone.utc), response="YES"
    )

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message=f"REDO-{draft.id} make it warmer")

    assert response.status_code == 200
    assert "Already handled" in sent_calls[0][1]


def test_redo_then_yes_still_works_after_reset(client, db_session, monkeypatch):
    # Confirms the approval-request reset done by a REDO doesn't break the normal YES/NO path
    # for the same code afterward.
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-redo-4")
    user = _create_user(db_session, email="approval-webhook-redo-4@example.com", phone="+31611120004")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    draft = _create_draft(db_session, tenant)
    _create_approval_request(db_session, draft, user)

    def fake_regenerate(db, draft_arg, instructions):
        draft_arg.generated_text = "Revised text."
        draft_arg.status = "pending"
        return draft_arg

    monkeypatch.setattr(ai_auto_draft_service, "regenerate_draft_via_planner", fake_regenerate)

    async def fake_broadcast_send(to, message, external_account_id=None):
        return {}

    monkeypatch.setattr(ai_draft_notification_service, "send_system_whatsapp_message", fake_broadcast_send)
    sent_calls = _patch_confirmation_send(monkeypatch)

    redo_response = _post_reply(client, sender=user.phone, message=f"REDO-{draft.id} shorter please")
    assert redo_response.status_code == 200

    def fake_send_scheduled_draft(db, draft_arg):
        draft_arg.status = "sent"
        return True

    monkeypatch.setattr(ai_auto_draft_service, "send_scheduled_draft", fake_send_scheduled_draft)

    yes_response = _post_reply(client, sender=user.phone, message=f"YES-{draft.id}")
    assert yes_response.status_code == 200
    assert "Sent to" in sent_calls[-1][1]

    db_session.refresh(draft)
    assert draft.status == "sent"


def test_reply_without_code_falls_through(client, db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_id="B-approval-webhook-6")
    user = _create_user(db_session, email="approval-webhook-no-code@example.com", phone="+31611117777")
    db_session.add(AdminSettings(notification_whatsapp_external_account_id=NOTIFICATION_ACCOUNT_ID))
    db_session.commit()
    _create_draft(db_session, tenant)

    sent_calls = _patch_confirmation_send(monkeypatch)

    response = _post_reply(client, sender=user.phone, message="sounds good")

    assert response.status_code == 200
    assert response.json()["message"] == "inbound unresolved"
    assert sent_calls == []
