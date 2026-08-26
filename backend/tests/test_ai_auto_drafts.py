from datetime import datetime, timedelta, timezone

from app.models.ai_auto_draft import AiAutoDraft
from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage, GmailAccount
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.services import ai_auto_draft_service


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Pending Draft Tenant",
        booking_id="B-pending-draft-1",
        first_name="Sam",
        last_name="Doe",
        check_in="2026-08-01",
        check_out="2026-08-05",
        room_name="Studio 1",
    )
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_list_defaults_to_pending_statuses_across_tenants(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    pending = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft 1", status="pending")
    scheduled = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="draft 2", status="pending_auto_send")
    sent = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft 3", status="sent")
    db_session.add_all([pending, scheduled, sent])
    db_session.commit()

    response = non_admin_client.get("/api/ai-auto-drafts")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    # Other test modules that bypass the per-test transaction (real SessionLocal() commits, same
    # pattern as test_gmail_background_poll.py) can leave unrelated pending drafts in the shared
    # test database, so assert on presence/absence rather than exact set equality.
    assert {pending.id, scheduled.id}.issubset(ids)
    assert sent.id not in ids


def test_list_filters_by_tenant_and_channel(non_admin_client, db_session):
    tenant_a = _create_tenant(db_session, booking_id="B-pending-draft-a", name="Tenant A")
    tenant_b = _create_tenant(db_session, booking_id="B-pending-draft-b", name="Tenant B")
    draft_a = AiAutoDraft(tenant_id=tenant_a.id, channel="email", generated_text="a", status="pending")
    draft_b = AiAutoDraft(tenant_id=tenant_b.id, channel="whatsapp", generated_text="b", status="pending")
    db_session.add_all([draft_a, draft_b])
    db_session.commit()

    response = non_admin_client.get(f"/api/ai-auto-drafts?tenant_id={tenant_a.id}")
    assert [item["id"] for item in response.json()] == [draft_a.id]


def test_dismiss_and_mark_used(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/mark-used")
    assert response.status_code == 200
    assert response.json()["status"] == "used_as_manual_seed"

    draft2 = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="draft 2", status="pending")
    db_session.add(draft2)
    db_session.commit()
    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft2.id}/dismiss")
    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"

    # Neither shows up in the default pending listing anymore.
    listing = non_admin_client.get("/api/ai-auto-drafts").json()
    assert draft.id not in {item["id"] for item in listing}
    assert draft2.id not in {item["id"] for item in listing}


def test_dismiss_records_human_ui_resolution_reason(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/dismiss", json={"reason": "Guest cancelled the booking"})
    assert response.status_code == 200

    db_session.refresh(draft)
    assert draft.resolution_source == "human_ui"
    assert draft.resolution_reason == "Guest cancelled the booking"


def test_dismiss_without_reason_leaves_resolution_reason_null(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/dismiss")
    assert response.status_code == 200

    db_session.refresh(draft)
    assert draft.resolution_source == "human_ui"
    assert draft.resolution_reason is None


def test_send_scheduled_draft_auto_timer_falls_back_to_checker_feedback(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="whatsapp",
        generated_text="draft",
        status="pending_auto_send",
        checker_feedback="Checker approved: matches template tone.",
    )
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "_send_whatsapp_draft", lambda db, draft_arg: (True, None))

    sent, failure_reason = ai_auto_draft_service.send_scheduled_draft(db_session, draft, resolution_source="auto_timer")

    assert sent is True
    assert failure_reason is None
    assert draft.status == "sent"
    assert draft.resolution_source == "auto_timer"
    assert draft.resolution_reason == "Checker approved: matches template tone."


def test_send_scheduled_draft_human_ui_uses_explicit_reason(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "_send_whatsapp_draft", lambda db, draft_arg: (True, None))

    sent, failure_reason = ai_auto_draft_service.send_scheduled_draft(db_session, draft, resolution_source="human_ui", reason="Confirmed by phone")

    assert sent is True
    assert failure_reason is None
    assert draft.resolution_source == "human_ui"
    assert draft.resolution_reason == "Confirmed by phone"


def test_cancel_auto_send_downgrades_to_pending(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="email",
        generated_text="draft",
        status="pending_auto_send",
        scheduled_send_at=datetime.now(timezone.utc),
    )
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/cancel-auto-send")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["scheduled_send_at"] is None

    # Still visible in the default pending listing, just no longer scheduled.
    listing = non_admin_client.get("/api/ai-auto-drafts").json()
    assert draft.id in {item["id"] for item in listing}


def test_cancel_auto_send_is_a_no_op_when_not_scheduled(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/cancel-auto-send")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_send_now_rejects_whatsapp_ambiguity_with_actionable_detail(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    db_session.add_all(
        [
            TenantChannelEndpoint(tenant_id=tenant.id, channel_type="whatsapp", provider="whatsapp-service", external_account_id="acct-a", external_chat_namespace="a@c.us", is_active=True),
            TenantChannelEndpoint(tenant_id=tenant.id, channel_type="whatsapp", provider="whatsapp-service", external_account_id="acct-b", external_chat_namespace="b@c.us", is_active=True),
        ]
    )
    db_session.commit()

    draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="Hi there", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/send-now")

    assert response.status_code == 400
    assert response.json()["detail"] == "This tenant has multiple WhatsApp chats linked; link a specific one for this draft"


def test_send_now_returns_502_for_provider_exception(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    account = GmailAccount(email_address="inbox-send-now-fail@example.com", is_active=True)
    db_session.add(account)
    db_session.flush()
    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-send-now-fail", subject="Hi")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id="msg-send-now-fail",
            direction="inbound",
            sender_email="tenant-send-now-fail@example.com",
            subject="Hi",
            body="When is check-in?",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="email",
        email_thread_id=conversation.id,
        generated_text="Check-in is at 3pm",
        status="pending",
    )
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "build_gmail_credentials", lambda account: object())

    def failing_send(credentials, **kwargs):
        raise RuntimeError("gmail api down")

    monkeypatch.setattr(ai_auto_draft_service, "send_gmail_reply", failing_send)

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/send-now")

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to send Gmail reply"


def test_send_now_sends_pending_draft_and_marks_sent(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    account = GmailAccount(email_address="inbox-send-now@example.com", is_active=True)
    db_session.add(account)
    db_session.flush()
    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-send-now", subject="Hi")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id="msg-send-now",
            direction="inbound",
            sender_email="tenant-send-now@example.com",
            subject="Hi",
            body="When is check-in?",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="email",
        email_thread_id=conversation.id,
        generated_text="Check-in is at 3pm",
        status="pending",
    )
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "build_gmail_credentials", lambda account: object())
    monkeypatch.setattr(ai_auto_draft_service, "send_gmail_reply", lambda credentials, **kwargs: {"id": "gmail-msg-id"})

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/send-now")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"

    db_session.refresh(draft)
    assert draft.sent_communication_id is not None
    communication = db_session.query(Communication).filter(Communication.id == draft.sent_communication_id).first()
    assert communication.ai_generated is True


def test_send_now_failure_leaves_draft_pending_and_returns_502(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    account = GmailAccount(email_address="inbox-send-now-fail@example.com", is_active=True)
    db_session.add(account)
    db_session.flush()
    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-send-now-fail", subject="Hi")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id="msg-send-now-fail",
            direction="inbound",
            sender_email="tenant-send-now-fail@example.com",
            subject="Hi",
            body="When is check-in?",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="email",
        email_thread_id=conversation.id,
        generated_text="Check-in is at 3pm",
        status="pending",
    )
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "build_gmail_credentials", lambda account: object())

    def failing_send(credentials, **kwargs):
        raise RuntimeError("gmail api down")

    monkeypatch.setattr(ai_auto_draft_service, "send_gmail_reply", failing_send)

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/send-now")
    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to send Gmail reply"

    db_session.refresh(draft)
    assert draft.status == "pending"
    assert draft.sent_communication_id is None


def test_send_now_rejects_when_latest_reply_points_to_our_own_mailbox(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    account = GmailAccount(email_address="inbox-own-mailbox@example.com", is_active=True)
    sibling_account = GmailAccount(email_address="info@shortstayinn.com", is_active=True)
    db_session.add_all([account, sibling_account])
    db_session.flush()
    conversation = Conversation(provider="gmail", provider_account_id=account.id, provider_thread_id="thread-own-mailbox", subject="Hi")
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
            subject="Re: Hi",
            body="Forwarded internally",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    db_session.commit()

    draft = AiAutoDraft(
        tenant_id=tenant.id,
        channel="email",
        email_thread_id=conversation.id,
        generated_text="Check-in is at 3pm",
        status="pending",
    )
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "build_gmail_credentials", lambda account: object())
    monkeypatch.setattr(
        ai_auto_draft_service,
        "send_gmail_reply",
        lambda credentials, **kwargs: (_ for _ in ()).throw(AssertionError("send_gmail_reply should not be called")),
    )

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/send-now")
    assert response.status_code == 400
    assert response.json()["detail"] == "Could not determine a recipient email for this thread"

    db_session.refresh(draft)
    assert draft.status == "pending"
    assert draft.sent_communication_id is None


def test_send_now_rejects_already_sent_draft(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="sent")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/send-now")
    assert response.status_code == 409


def test_redo_regenerates_draft_and_logs_the_request(non_admin_client, db_session, monkeypatch):
    """The CRM counterpart to the WhatsApp REDO reply - reached from the thread view's inline
    draft banner instead of a WhatsApp text reply."""
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="Hi there!", status="pending")
    db_session.add(draft)
    db_session.commit()

    def fake_regenerate(db, draft_arg, what, why):
        assert what == "make it shorter"
        assert why == "they already asked yesterday"
        draft_arg.generated_text = "Shorter reply."
        draft_arg.status = "pending"
        draft_arg.agent_run_id = 22
        return draft_arg

    monkeypatch.setattr(ai_auto_draft_service, "regenerate_draft_via_planner", fake_regenerate)

    response = non_admin_client.put(
        f"/api/ai-auto-drafts/{draft.id}/redo",
        json={"what": "make it shorter", "why": "they already asked yesterday"},
    )

    assert response.status_code == 200
    assert response.json()["generated_text"] == "Shorter reply."

    log_entry = db_session.query(RedoRequestLog).filter(RedoRequestLog.ai_auto_draft_id == draft.id).one()
    assert log_entry.channel == "crm"
    assert log_entry.what == "make it shorter"
    assert log_entry.why == "they already asked yesterday"
    assert log_entry.ai_agent_run_id == 22


def test_redo_requires_what(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="Hi there!", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/redo", json={"what": "   "})

    assert response.status_code == 400


def test_redo_logs_failed_attempt_when_planner_produces_nothing(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="Hi there!", status="pending")
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(ai_auto_draft_service, "regenerate_draft_via_planner", lambda db, draft_arg, what, why: None)

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/redo", json={"what": "make it warmer"})

    assert response.status_code == 502
    log_entry = db_session.query(RedoRequestLog).filter(RedoRequestLog.ai_auto_draft_id == draft.id).one()
    assert log_entry.what == "make it warmer"
