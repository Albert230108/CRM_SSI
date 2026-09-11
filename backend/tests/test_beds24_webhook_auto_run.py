"""D3: a Beds24 booking webhook registers brain/action-writer triggers for the tenant when
webhook_auto_run_enabled (default true), and those still self-gate on brain/action enables."""
from app.models.action_writer_trigger import ActionWriterTrigger
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_brain_trigger import TenantBrainTrigger


async def fake_booking_fetch(booking_id):
    return {
        "id": booking_id, "roomName": "Studio 1", "firstName": "Web", "lastName": "Hook",
        "arrival": "2026-08-01", "departure": "2026-08-05", "invoiceItems": [],
    }


def _no_info_items():
    async def _f(booking_id):
        return []
    return _f


def _patch_beds24(monkeypatch):
    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)
    monkeypatch.setattr("app.api.beds24_webhooks.get_booking_info_items", _no_info_items())


def _triggers(db_session, tenant_id):
    brain = db_session.query(TenantBrainTrigger).filter(TenantBrainTrigger.tenant_id == tenant_id).all()
    action = db_session.query(ActionWriterTrigger).filter(ActionWriterTrigger.tenant_id == tenant_id).all()
    return brain, action


def test_webhook_registers_triggers_when_auto_run_and_writers_enabled(client, db_session, monkeypatch):
    _patch_beds24(monkeypatch)
    existing = Tenant(booking_id="WH-AUTORUN-ON", name="Old")
    db_session.add(existing)
    db_session.commit()
    db_session.add(TenantAiSettings(
        tenant_id=existing.id, webhook_auto_run_enabled=True,
        brain_writer_enabled=True, action_writer_enabled=True,
    ))
    db_session.commit()

    assert client.get("/api/webhooks/beds24", params={"bookid": "WH-AUTORUN-ON", "status": "modify"}).status_code == 200

    brain, action = _triggers(db_session, existing.id)
    assert len(brain) == 1 and brain[0].channel == "beds24"
    assert len(action) == 1 and action[0].channel == "beds24"


def test_webhook_skips_triggers_when_auto_run_disabled(client, db_session, monkeypatch):
    _patch_beds24(monkeypatch)
    existing = Tenant(booking_id="WH-AUTORUN-OFF", name="Old")
    db_session.add(existing)
    db_session.commit()
    db_session.add(TenantAiSettings(
        tenant_id=existing.id, webhook_auto_run_enabled=False,
        brain_writer_enabled=True, action_writer_enabled=True,
    ))
    db_session.commit()

    assert client.get("/api/webhooks/beds24", params={"bookid": "WH-AUTORUN-OFF", "status": "modify"}).status_code == 200

    brain, action = _triggers(db_session, existing.id)
    assert brain == [] and action == []


def test_webhook_auto_run_still_gated_on_writer_enables(client, db_session, monkeypatch):
    """Auto-run on but brain/action writers off (the default) => the triggers self-gate to nothing."""
    _patch_beds24(monkeypatch)
    existing = Tenant(booking_id="WH-AUTORUN-WRITERS-OFF", name="Old")
    db_session.add(existing)
    db_session.commit()
    db_session.add(TenantAiSettings(tenant_id=existing.id, webhook_auto_run_enabled=True))  # writers default off
    db_session.commit()

    assert client.get("/api/webhooks/beds24", params={"bookid": "WH-AUTORUN-WRITERS-OFF", "status": "modify"}).status_code == 200

    brain, action = _triggers(db_session, existing.id)
    assert brain == [] and action == []
