from datetime import datetime, timedelta, timezone

from app.models.ai_auto_draft import AiAutoDraft
from app.models.ai_auto_draft_trigger import AiAutoDraftTrigger
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.services.ai_draft_trigger_service import register_inbound_message


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Trigger Tenant",
        booking_id="B-trigger-1",
        first_name="Sam",
        last_name="Doe",
        email="sam@example.com",
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


def test_no_trigger_when_auto_draft_disabled(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_email=False))
    db_session.commit()

    register_inbound_message(db_session, tenant=tenant, channel="email")
    db_session.commit()

    assert db_session.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).count() == 0


def test_no_trigger_when_no_ai_settings_row_exists(db_session):
    tenant = _create_tenant(db_session)
    register_inbound_message(db_session, tenant=tenant, channel="email")
    db_session.commit()
    assert db_session.query(AiAutoDraftTrigger).count() == 0


def test_creates_and_debounces_trigger(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_email=True))
    db_session.commit()

    register_inbound_message(db_session, tenant=tenant, channel="email", email_thread_id=5)
    db_session.commit()

    trigger = db_session.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).one()
    first_trigger_at = trigger.trigger_at
    assert trigger.channel == "email"
    assert trigger.email_thread_id == 5

    # A second inbound message resets (pushes out) the debounce timer rather than creating a
    # second row - the unique (tenant_id, channel) constraint on the model enforces this too.
    register_inbound_message(db_session, tenant=tenant, channel="email", email_thread_id=5)
    db_session.commit()

    triggers = db_session.query(AiAutoDraftTrigger).filter(AiAutoDraftTrigger.tenant_id == tenant.id).all()
    assert len(triggers) == 1
    assert triggers[0].trigger_at >= first_trigger_at


def test_supersedes_pending_draft_on_new_message(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_whatsapp=True))
    db_session.commit()
    pending_draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="stale draft", status="pending")
    db_session.add(pending_draft)
    db_session.commit()

    register_inbound_message(db_session, tenant=tenant, channel="whatsapp")
    db_session.commit()
    db_session.refresh(pending_draft)

    assert pending_draft.status == "superseded"


def test_does_not_supersede_drafts_on_other_channels(db_session):
    tenant = _create_tenant(db_session)
    db_session.add(TenantAiSettings(tenant_id=tenant.id, auto_draft_email=True))
    db_session.commit()
    whatsapp_draft = AiAutoDraft(tenant_id=tenant.id, channel="whatsapp", generated_text="unrelated", status="pending")
    db_session.add(whatsapp_draft)
    db_session.commit()

    register_inbound_message(db_session, tenant=tenant, channel="email")
    db_session.commit()
    db_session.refresh(whatsapp_draft)

    assert whatsapp_draft.status == "pending"
