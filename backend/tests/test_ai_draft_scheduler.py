from datetime import datetime, timedelta, timezone

import app.main as main_module
from app.database import SessionLocal
from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.ai_reply_template import AiReplyTemplate
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.user import User
from app.services import ai_reply_service


def _setup(db, *, booking_id: str, with_default_template: bool = True):
    user = db.query(User).filter(User.email == "scheduler-owner@example.com").first()
    if user is None:
        user = User(email="scheduler-owner@example.com", password_hash="x", is_active=True, is_admin=False)
        db.add(user)
        db.flush()

    tenant = Tenant(
        name="Scheduler Tenant",
        booking_id=booking_id,
        first_name="Sam",
        last_name="Doe",
        check_in="2026-08-01",
        check_out="2026-08-05",
        room_name="Studio 1",
    )
    db.add(tenant)
    db.flush()

    template = AiReplyTemplate(
        name="Scheduler template",
        sections=[{"label": "Persona", "content": "Be helpful."}],
        created_by_user_id=user.id,
    )
    db.add(template)
    db.flush()

    ai_settings = TenantAiSettings(
        tenant_id=tenant.id,
        default_email_template_id=template.id if with_default_template else None,
        auto_draft_email=True,
    )
    db.add(ai_settings)
    db.commit()
    return tenant, template


def _teardown(db, tenant, template):
    # These tests use real SessionLocal() (like test_gmail_background_poll.py) so the scheduler
    # code path runs exactly as it does in production - but that means commits here persist in
    # the shared test database beyond this test, unlike the transactional db_session fixture.
    # Clean up explicitly so later tests in the same run don't see leftover rows.
    db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).delete()
    db.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant.id).delete()
    db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).delete()
    db.query(Tenant).filter(Tenant.id == tenant.id).delete()
    db.query(AiReplyTemplate).filter(AiReplyTemplate.id == template.id).delete()
    db.commit()


def test_due_trigger_generates_draft_and_is_removed(monkeypatch):
    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", lambda prompt: "Auto-generated reply")

    db = SessionLocal()
    tenant = template = None
    try:
        tenant, template = _setup(db, booking_id="B-scheduler-1")
        db.add(AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()

        main_module._run_due_ai_draft_triggers_once()

        drafts = db.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant.id).all()
        assert len(drafts) == 1
        assert drafts[0].status == "pending"
        assert drafts[0].generated_text == "Auto-generated reply"
        assert drafts[0].template_id == template.id
        assert db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).count() == 0
    finally:
        if tenant is not None:
            _teardown(db, tenant, template)
        db.close()


def test_trigger_not_yet_due_is_left_alone(monkeypatch):
    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", lambda prompt: "should not be called")

    db = SessionLocal()
    tenant = template = None
    try:
        tenant, template = _setup(db, booking_id="B-scheduler-2")
        db.add(AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc) + timedelta(minutes=5)))
        db.commit()

        main_module._run_due_ai_draft_triggers_once()

        assert db.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant.id).count() == 0
        assert db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).count() == 1
    finally:
        if tenant is not None:
            _teardown(db, tenant, template)
        db.close()


def test_trigger_without_default_template_is_skipped_and_removed(monkeypatch):
    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", lambda prompt: "should not be called")

    db = SessionLocal()
    tenant = template = None
    try:
        tenant, template = _setup(db, booking_id="B-scheduler-3", with_default_template=False)
        db.add(AiAutoDraftTrigger(tenant_id=tenant.id, channel="email", trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()

        main_module._run_due_ai_draft_triggers_once()

        assert db.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant.id).count() == 0
        # A permanently-unresolvable trigger (no default template) must still be consumed, not
        # retried forever - the next inbound message re-registers a fresh trigger anyway.
        assert db.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).count() == 0
    finally:
        if tenant is not None:
            _teardown(db, tenant, template)
        db.close()
