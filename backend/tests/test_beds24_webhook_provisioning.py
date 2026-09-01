"""Regression tests for two provisioning gaps in the live Beds24 webhook
(_process_beds24_booking_event, app.api.beds24_webhooks): a newly-created tenant used to skip
the admin-configured AI planner default, and a CRM_EMAIL info item linked automatically here used
to never trigger a Gmail history sync for the newly-linked address.
"""
from app.models.admin_settings import AdminSettings
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_email_address import TenantEmailAddress


async def fake_booking_fetch(booking_id):
    return {
        "id": booking_id,
        "roomName": "Studio 1",
        "firstName": "Web",
        "lastName": "Hook",
        "arrival": "2026-08-01",
        "departure": "2026-08-05",
        "invoiceItems": [],
    }


def _fake_info_items_returning(items):
    async def fake_get_booking_info_items(booking_id):
        return items

    return fake_get_booking_info_items


def test_webhook_seeds_planner_default_for_a_newly_created_tenant(client, db_session, monkeypatch):
    db_session.add(AdminSettings(planner_default_mode="auto-draft"))
    db_session.commit()

    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)
    monkeypatch.setattr("app.api.beds24_webhooks.get_booking_info_items", _fake_info_items_returning([]))

    response = client.get("/api/webhooks/beds24", params={"bookid": "WEBHOOK-PLANNER-DEFAULT", "status": "new"})
    assert response.status_code == 200

    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "WEBHOOK-PLANNER-DEFAULT").first()
    assert tenant is not None

    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    assert settings is not None
    assert settings.planner_mode == "auto-draft"
    # "auto-draft" is meaningless unless the per-channel auto_draft triggers are on, so seeding must
    # switch them on too (mirroring the settings endpoints). Without this the imported booking shows
    # auto-draft selected but never actually drafts. auto_send stays off until an explicit opt-in.
    assert settings.auto_draft_email is True
    assert settings.auto_draft_whatsapp is True
    assert settings.auto_send_email is False
    assert settings.auto_send_whatsapp is False


def test_webhook_seeds_auto_send_default_with_draft_triggers_on(client, db_session, monkeypatch):
    db_session.add(AdminSettings(planner_default_mode="auto-send"))
    db_session.commit()

    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)
    monkeypatch.setattr("app.api.beds24_webhooks.get_booking_info_items", _fake_info_items_returning([]))

    response = client.get("/api/webhooks/beds24", params={"bookid": "WEBHOOK-AUTOSEND-DEFAULT", "status": "new"})
    assert response.status_code == 200

    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "WEBHOOK-AUTOSEND-DEFAULT").first()
    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).first()
    assert settings.planner_mode == "auto-send"
    assert settings.auto_draft_email is True
    assert settings.auto_draft_whatsapp is True
    # auto-send mode still requires an explicit opt-in for the auto_send toggles (endpoints don't
    # auto-enable them either), so seeding leaves them at their False default.
    assert settings.auto_send_email is False
    assert settings.auto_send_whatsapp is False


def test_webhook_does_not_retrofit_planner_mode_for_an_existing_tenant(client, db_session, monkeypatch):
    db_session.add(AdminSettings(planner_default_mode="auto-draft"))
    existing = Tenant(booking_id="WEBHOOK-PLANNER-EXISTING", name="Old Name")
    db_session.add(existing)
    db_session.commit()
    db_session.add(TenantAiSettings(tenant_id=existing.id, planner_mode="off"))
    db_session.commit()

    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)
    monkeypatch.setattr("app.api.beds24_webhooks.get_booking_info_items", _fake_info_items_returning([]))

    response = client.get("/api/webhooks/beds24", params={"bookid": "WEBHOOK-PLANNER-EXISTING", "status": "modify"})
    assert response.status_code == 200

    settings = db_session.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == existing.id).first()
    assert settings.planner_mode == "off"


def test_webhook_triggers_gmail_sync_for_a_newly_linked_crm_email(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)
    monkeypatch.setattr(
        "app.api.beds24_webhooks.get_booking_info_items",
        _fake_info_items_returning([{"id": 555, "code": "CRM_EMAIL", "text": "guest@example.com"}]),
    )

    started_jobs = []

    def fake_start_job(kind, awaitable, job_id=None):
        started_jobs.append((kind, awaitable))
        awaitable.close()  # never actually run in this test; avoid an "unawaited coroutine" warning
        return "fake-job-id"

    monkeypatch.setattr("app.api.beds24_webhooks.start_job", fake_start_job)

    sync_calls = []
    monkeypatch.setattr("app.api.beds24_webhooks.sync_email_across_gmail_accounts", lambda email: sync_calls.append(email))

    response = client.get("/api/webhooks/beds24", params={"bookid": "WEBHOOK-CRM-EMAIL-NEW", "status": "new"})
    assert response.status_code == 200

    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "WEBHOOK-CRM-EMAIL-NEW").first()
    assert tenant is not None
    link = db_session.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant.id).first()
    assert link is not None
    assert link.email == "guest@example.com"

    assert len(started_jobs) == 1
    assert started_jobs[0][0] == "gmail_sync_email"


def test_webhook_does_not_resync_an_already_linked_crm_email(client, db_session, monkeypatch):
    """A CRM_EMAIL that was already linked on a previous sync must not trigger another full
    Gmail history search every time the same webhook event repeats for that booking."""
    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)
    monkeypatch.setattr(
        "app.api.beds24_webhooks.get_booking_info_items",
        _fake_info_items_returning([{"id": 556, "code": "CRM_EMAIL", "text": "already-linked@example.com"}]),
    )

    started_jobs = []

    def fake_start_job(kind, awaitable, job_id=None):
        started_jobs.append((kind, awaitable))
        awaitable.close()
        return "fake-job-id"

    monkeypatch.setattr("app.api.beds24_webhooks.start_job", fake_start_job)
    monkeypatch.setattr("app.api.beds24_webhooks.sync_email_across_gmail_accounts", lambda email: None)

    # First delivery: creates the tenant and links the address, firing one sync job.
    response = client.get("/api/webhooks/beds24", params={"bookid": "WEBHOOK-CRM-EMAIL-REPEAT", "status": "new"})
    assert response.status_code == 200
    assert len(started_jobs) == 1

    # Second delivery for the same booking with the same CRM_EMAIL: the address is already
    # linked, so no new job should fire.
    response = client.get("/api/webhooks/beds24", params={"bookid": "WEBHOOK-CRM-EMAIL-REPEAT", "status": "modify"})
    assert response.status_code == 200
    assert len(started_jobs) == 1
