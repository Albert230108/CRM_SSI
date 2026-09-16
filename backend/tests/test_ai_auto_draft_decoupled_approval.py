"""Regression tests for decoupled message vs Beds24 approvals on AI auto-drafts.

Message replies and prepared Beds24 actions are approved independently in the AI Drafts UI:

- The CRM "Send" (resolution_source="human_ui") sends the reply only - it never pushes the staged
  Beds24 action (that stays for its own approval). The WhatsApp YES / auto-timer paths keep the
  original coupled behaviour (covered in test_ai_auto_drafts.py).
- PUT /execute-now approves + pushes the Beds24 action on its own, without sending the reply.
- PUT /reject-execution drops the Beds24 action but keeps the message draft, logging an escalated
  executor run for the audit trail.
- A draft whose message was already sent but that still carries a pending Beds24 action is not
  orphaned: the list endpoint still returns it so the Beds24 column can act on it.
"""

from app.models.ai_agent_run import AiAgentRun
from app.models.ai_auto_draft import AiAutoDraft
from app.models.tenant import Tenant
from app.services import ai_agent_orchestrator, ai_auto_draft_service


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Decoupled Tenant", booking_id="B-decoupled-1", first_name="Sam", last_name="Doe",
        check_in="2026-08-01", check_out="2026-08-05", room_name="Studio 1",
    )
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _pending_execution(tenant, **overrides):
    payload = {
        "action": "update",
        "booking_id": tenant.booking_id,
        "invoice_items": [{"type": "charge", "description": "Studio 1", "qty": 4, "amount": 100, "vat_rate": 9}],
    }
    payload.update(overrides)
    return payload


def _stub_executor(monkeypatch, *, approved: bool, reason: str = "", run_id: int | None = 999):
    def fake(db, *, tenant, pending_execution, price_context="", is_redo=False):
        return ai_agent_orchestrator.ExecutorResult(approved=approved, reason=reason), run_id

    monkeypatch.setattr(ai_agent_orchestrator, "run_executor_validation", fake)


def test_crm_send_now_sends_message_only_and_leaves_beds24_pending(db_session, monkeypatch):
    """The decoupling contract: a CRM (human_ui) send delivers the reply but must NOT validate or
    push the staged Beds24 action - it stays "pending" for its own approval."""
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(
        tenant_id=tenant.id, channel="whatsapp", generated_text="Updated price: EUR 400",
        status="pending", pending_execution=_pending_execution(tenant), execution_status="pending",
    )
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr(
        ai_agent_orchestrator, "run_executor_validation",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("CRM send must not run the executor")),
    )
    monkeypatch.setattr(
        ai_auto_draft_service.beds24_service, "update_booking_invoice_items",
        lambda **k: (_ for _ in ()).throw(AssertionError("CRM send must not push to Beds24")),
    )
    monkeypatch.setattr(ai_auto_draft_service, "_send_whatsapp_draft", lambda db, draft_arg: (True, None))

    sent, failure_reason = ai_auto_draft_service.send_scheduled_draft(db_session, draft, resolution_source="human_ui")

    assert sent is True
    assert failure_reason is None
    assert draft.status == "sent"
    # The Beds24 action is untouched - still staged, still awaiting its own approval.
    assert draft.pending_execution is not None
    assert draft.execution_status == "pending"


def test_execute_now_pushes_beds24_without_sending_message(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(
        tenant_id=tenant.id, channel="whatsapp", generated_text="Updated price: EUR 400",
        status="pending", pending_execution=_pending_execution(tenant), execution_status="pending",
    )
    db_session.add(draft)
    db_session.commit()

    calls = {}

    async def fake_update(*, booking_id, original_invoice_item_ids, final_invoice_items):
        calls["update"] = booking_id

    async def fake_sync(db_arg, booking_id_arg):
        calls["sync"] = booking_id_arg
        return tenant

    monkeypatch.setattr(ai_auto_draft_service.beds24_service, "update_booking_invoice_items", fake_update)
    monkeypatch.setattr(ai_auto_draft_service, "sync_tenant_from_beds24_booking", fake_sync)
    _stub_executor(monkeypatch, approved=True, reason="Guest confirmed the new price")
    monkeypatch.setattr(
        ai_auto_draft_service, "_send_whatsapp_draft",
        lambda db, draft_arg: (_ for _ in ()).throw(AssertionError("execute-now must not send the message")),
    )

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/execute-now")
    assert response.status_code == 200
    body = response.json()
    assert body["execution_status"] == "executed"
    assert body["has_pending_execution"] is False
    # The message reply is untouched - still pending its own approval.
    assert body["status"] == "pending"

    db_session.refresh(draft)
    assert draft.pending_execution is None
    assert draft.execution_status == "executed"
    assert draft.executor_run_id == 999
    assert calls == {"update": tenant.booking_id, "sync": tenant.booking_id}


def test_execute_now_blocks_and_marks_failed_when_executor_rejects(non_admin_client, db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(
        tenant_id=tenant.id, channel="whatsapp", generated_text="Updated price",
        status="pending", pending_execution=_pending_execution(tenant), execution_status="pending",
    )
    db_session.add(draft)
    db_session.commit()

    _stub_executor(monkeypatch, approved=False, reason="Guest never confirmed the new price", run_id=7)
    monkeypatch.setattr(
        ai_auto_draft_service.beds24_service, "update_booking_invoice_items",
        lambda **k: (_ for _ in ()).throw(AssertionError("Must not push when the executor rejects")),
    )

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/execute-now")
    assert response.status_code == 502
    assert response.json()["detail"] == "Guest never confirmed the new price"

    db_session.refresh(draft)
    # The staged action is kept (a rejection is recoverable), but flagged failed for the UI warn.
    assert draft.pending_execution is not None
    assert draft.execution_status == "failed"
    assert draft.executor_run_id == 7


def test_execute_now_409_when_no_beds24_action(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/execute-now")
    assert response.status_code == 409


def test_reject_execution_keeps_message_and_logs_escalated_run(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(
        tenant_id=tenant.id, channel="whatsapp", generated_text="Updated price",
        status="pending", pending_execution=_pending_execution(tenant), execution_status="pending",
    )
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(
        f"/api/ai-auto-drafts/{draft.id}/reject-execution", json={"reason": "Price not agreed yet"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["execution_status"] == "rejected"
    assert body["has_pending_execution"] is False
    # The message draft survives so the reply can still be sent or edited separately.
    assert body["status"] == "pending"

    db_session.refresh(draft)
    assert draft.pending_execution is None
    assert draft.execution_status == "rejected"
    run = db_session.query(AiAgentRun).filter(AiAgentRun.id == draft.executor_run_id).one()
    assert run.channel == "beds24"
    assert run.status == ai_agent_orchestrator.STATUS_ESCALATED
    assert run.escalation_reason == "human_rejected"
    assert "Price not agreed yet" in run.final_text


def test_reject_execution_409_when_no_beds24_action(non_admin_client, db_session):
    tenant = _create_tenant(db_session)
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="draft", status="pending")
    db_session.add(draft)
    db_session.commit()

    response = non_admin_client.put(f"/api/ai-auto-drafts/{draft.id}/reject-execution")
    assert response.status_code == 409


def test_list_returns_sent_draft_with_pending_beds24_action(non_admin_client, db_session):
    """A message can be sent while its Beds24 action is still pending (warn-only linkage). The list
    must still surface that draft so the Beds24 approval is never orphaned once the message is sent."""
    tenant = _create_tenant(db_session)
    lingering = AiAutoDraft(
        tenant_id=tenant.id, channel="whatsapp", generated_text="Sent already",
        status="sent", pending_execution=_pending_execution(tenant), execution_status="pending",
    )
    db_session.add(lingering)
    db_session.commit()

    items = {item["id"]: item for item in non_admin_client.get(f"/api/ai-auto-drafts?tenant_id={tenant.id}").json()}
    assert lingering.id in items
    assert items[lingering.id]["status"] == "sent"
    assert items[lingering.id]["execution_status"] == "pending"


def test_list_does_not_report_pending_beds24_when_payload_is_empty(non_admin_client, db_session):
    """Regression: the 0102 backfill stamped rows "pending" WHERE `pending_execution IS NOT NULL`,
    but a JSON `null`/`{}` payload is not SQL NULL, so empty-payload rows were wrongly marked
    "pending". They rendered an un-actionable Beds24 card whose approve/reject endpoints 409 for
    having no payload. The read guard must normalise those back: no executor run -> no action;
    an executor run already fired -> "executed"."""
    tenant = _create_tenant(db_session)
    # No payload at all, and an empty-dict payload: both are falsy in Python but not SQL NULL.
    null_payload = AiAutoDraft(
        tenant_id=tenant.id, channel="whatsapp", generated_text="ghost, no payload",
        status="sent", pending_execution=None, execution_status="pending",
    )
    empty_payload = AiAutoDraft(
        tenant_id=tenant.id, channel="whatsapp", generated_text="ghost, empty payload",
        status="sent", pending_execution={}, execution_status="pending",
    )
    already_executed = AiAutoDraft(
        tenant_id=tenant.id, channel="whatsapp", generated_text="ghost, already pushed",
        status="sent", pending_execution=None, execution_status="pending", executor_run_id=999,
    )
    db_session.add_all([null_payload, empty_payload, already_executed])
    db_session.commit()

    items = {item["id"]: item for item in non_admin_client.get(f"/api/ai-auto-drafts?tenant_id={tenant.id}").json()}

    for ghost in (null_payload, empty_payload):
        assert items[ghost.id]["execution_status"] is None
        assert items[ghost.id]["has_pending_execution"] is False
    # An empty payload but a recorded executor run means the push already happened.
    assert items[already_executed.id]["execution_status"] == "executed"
    assert items[already_executed.id]["has_pending_execution"] is False
