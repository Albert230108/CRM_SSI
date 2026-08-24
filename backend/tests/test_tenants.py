from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

import pytest

from app.api.tenants import list_tenant_statuses, list_tenants
from app.core.dependencies import get_current_user
from app.main import app
from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.notification import Notification, NotificationReadState
from app.models.tenant import Tenant
from app.models.tenant_brain_entry import TenantBrainEntry
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_email_address import TenantEmailAddress
from app.models.tenant_notes_history import TenantNotesHistory
from app.models.user import User
from app.services import tenant_brain_service

CREATE_TENANT_USER = User(id=3, email="creator@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: CREATE_TENANT_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def create_tenant(db_session, name='Tenant A', booking_id='B-1'):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_endpoint(db_session, tenant_id, external_account_id, webhook_token):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type='whatsapp',
        provider='whatsapp-service',
        external_account_id=external_account_id,
        webhook_token=webhook_token,
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint

async def fake_whatsapp_booking(booking_id):
    return {
        "id": booking_id,
        "roomName": "Studio 1",
        "arrival": "2026-07-01",
        "departure": "2026-07-02",
        "invoiceItems": [],
    }


def test_delete_tenant_without_endpoints_succeeds(client, db_session):
    tenant = create_tenant(db_session, name='Tenant Delete A', booking_id='DEL-A')

    response = client.delete(f'/api/tenants/{tenant.id}')

    assert response.status_code == 204
    assert db_session.query(Tenant).filter(Tenant.id == tenant.id).first() is None


def test_delete_tenant_with_endpoints_deletes_endpoints_too(client, db_session):
    tenant = create_tenant(db_session, name='Tenant Delete B', booking_id='DEL-B')
    create_endpoint(db_session, tenant.id, 'client-delete-b-1', 'token-delete-b-1')
    create_endpoint(db_session, tenant.id, 'client-delete-b-2', 'token-delete-b-2')

    response = client.delete(f'/api/tenants/{tenant.id}')

    assert response.status_code == 204
    assert db_session.query(Tenant).filter(Tenant.id == tenant.id).first() is None
    assert db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant.id).count() == 0


def test_delete_tenant_with_notes_history_succeeds(client, db_session):
    tenant = create_tenant(db_session, name='Tenant Delete D', booking_id='DEL-D')
    db_session.add(TenantNotesHistory(tenant_id=tenant.id, old_value=None, new_value='note', source='manual'))
    db_session.commit()

    response = client.delete(f'/api/tenants/{tenant.id}')

    assert response.status_code == 204
    assert db_session.query(Tenant).filter(Tenant.id == tenant.id).first() is None
    assert db_session.query(TenantNotesHistory).filter(TenantNotesHistory.tenant_id == tenant.id).count() == 0


def test_delete_tenant_with_email_address_succeeds(client, db_session):
    tenant = create_tenant(db_session, name='Tenant Delete E', booking_id='DEL-E')
    db_session.add(TenantEmailAddress(tenant_id=tenant.id, email='tenant-e@example.com'))
    db_session.commit()

    response = client.delete(f'/api/tenants/{tenant.id}')

    assert response.status_code == 204
    assert db_session.query(Tenant).filter(Tenant.id == tenant.id).first() is None
    assert db_session.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant.id).count() == 0


def test_tenant_email_api_prefers_legacy_column_and_falls_back_to_linked_email(user_client, db_session):
    tenant_linked_only = create_tenant(db_session, name="Linked Only Tenant", booking_id="EMAIL-LINKED")
    db_session.add(TenantEmailAddress(tenant_id=tenant_linked_only.id, email="linked-only@example.com", is_active=True))

    tenant_legacy = create_tenant(db_session, name="Legacy Tenant", booking_id="EMAIL-LEGACY")
    tenant_legacy.email = "legacy@example.com"
    db_session.add(TenantEmailAddress(tenant_id=tenant_legacy.id, email="linked-wins@example.com", is_active=True))
    db_session.commit()

    detail_linked = user_client.get(f"/api/tenants/{tenant_linked_only.id}")
    assert detail_linked.status_code == 200
    assert detail_linked.json()["email"] == "linked-only@example.com"

    detail_legacy = user_client.get(f"/api/tenants/{tenant_legacy.id}")
    assert detail_legacy.status_code == 200
    assert detail_legacy.json()["email"] == "legacy@example.com"

    listing = user_client.get("/api/tenants").json()
    by_id = {item["id"]: item for item in listing}
    assert by_id[tenant_linked_only.id]["email"] == "linked-only@example.com"
    assert by_id[tenant_legacy.id]["email"] == "legacy@example.com"


def test_delete_tenant_with_conversation_link_succeeds(client, db_session):
    tenant = create_tenant(db_session, name='Tenant Delete F', booking_id='DEL-F')
    conversation = Conversation(provider='gmail', provider_thread_id='thread-delete-f-1', subject='Question')
    db_session.add(conversation)
    db_session.flush()
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, source='email_match'))
    db_session.commit()

    response = client.delete(f'/api/tenants/{tenant.id}')

    assert response.status_code == 204
    assert db_session.query(Tenant).filter(Tenant.id == tenant.id).first() is None
    assert db_session.query(TenantConversationLink).filter(TenantConversationLink.tenant_id == tenant.id).count() == 0


def test_delete_nonexistent_tenant_returns_404(client):
    response = client.delete('/api/tenants/999999')

    assert response.status_code == 404
    assert response.json()['detail'] == 'Tenant not found'


def test_delete_tenant_returns_controlled_error_when_commit_fails(client, db_session, monkeypatch):
    tenant = create_tenant(db_session, name='Tenant Delete C', booking_id='DEL-C')
    create_endpoint(db_session, tenant.id, 'client-delete-c-1', 'token-delete-c-1')

    def raise_integrity_error():
        raise IntegrityError('DELETE FROM tenants', {}, Exception('fk violation'))

    monkeypatch.setattr(db_session, 'commit', raise_integrity_error)

    response = client.delete(f'/api/tenants/{tenant.id}')

    assert response.status_code == 409
    assert response.json()['detail'] == 'Tenant could not be deleted because dependent records still exist'
    assert db_session.query(Tenant).filter(Tenant.id == tenant.id).first() is not None

def test_create_tenant_does_not_auto_create_whatsapp_endpoint(user_client, db_session, monkeypatch):
    """A WhatsApp chat may only be linked to a tenant through an explicit manual
    TenantChannelEndpoint mapping (see CLAUDE.md's WhatsApp invariants) - tenant creation must
    not auto-create a bare endpoint. This replaces a stale test that asserted the opposite; that
    assertion was never actually exercised because the plain `client` fixture 401s before it,
    and the auto-creation code path it checked for (`ensure_whatsapp_endpoint_for_tenant`) has
    no call sites anywhere in the app."""
    monkeypatch.setattr(tenant_brain_service.gemini_client, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no profile configured, should not be called")))
    response = user_client.post('/api/tenants', json={'booking_id': 'CREATE-A', 'name': 'Tenant Create A'})
    assert response.status_code == 201
    payload = response.json()
    assert payload["booking_id"] == "CREATE-A"
    endpoint = db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == payload["id"]).first()
    assert endpoint is None


def test_create_tenant_does_not_crash_on_property_name_field(user_client, db_session):
    """Regression test: property_name is a read-only computed property on Tenant, not a column -
    TenantCreate still accepts it (derived from room_name), so it must be excluded before
    constructing Tenant(**payload) rather than passed straight through."""
    response = user_client.post(
        '/api/tenants', json={'booking_id': 'CREATE-PROP', 'name': 'Tenant Create Prop', 'property_name': 'Should Be Ignored'}
    )
    assert response.status_code == 201


def test_create_tenant_runs_initial_brain_scan(user_client, db_session, monkeypatch):
    from app.models.ai_agent_profile import BRAIN_WRITER_ROLE, AiAgentProfile
    from app.services import gemini_client

    db_session.add(AiAgentProfile(name="Default Brain Writer", role=BRAIN_WRITER_ROLE, is_default=True))
    db_session.commit()

    def _fake_generate(prompt, *, model=None, temperature=None, max_output_tokens=None, response_schema=None):
        return gemini_client.GenerationResult(
            text="ignored",
            parsed={"should_remember": True, "entries": ["New tenant, no history yet."], "reasoning": "Initial scan."},
            model=model or "fake-model",
            prompt_tokens=1,
            output_tokens=1,
            latency_ms=1,
        )

    monkeypatch.setattr(tenant_brain_service.gemini_client, "generate", _fake_generate)

    response = user_client.post('/api/tenants', json={'booking_id': 'CREATE-SCAN', 'name': 'Tenant Create Scan'})
    assert response.status_code == 201
    tenant_id = response.json()["id"]

    entry = db_session.query(TenantBrainEntry).filter(TenantBrainEntry.tenant_id == tenant_id).one()
    assert entry.content == "New tenant, no history yet."
    assert entry.source == "scanner"

def test_import_tenant_creates_whatsapp_endpoint_mapping(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.tenants.fetch_booking_with_invoice", fake_whatsapp_booking)
    response = client.post('/api/tenants/import', json={
        "booking_id": "IMPORT-A",
        "name": "Tenant Import A",
        "first_name": "Import",
        "last_name": "Tenant",
        "check_in": "2026-07-01",
        "check_out": "2026-07-02",
    })
    assert response.status_code == 200
    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "IMPORT-A").first()
    assert tenant is not None
    endpoint = db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant.id, TenantChannelEndpoint.channel_type == "whatsapp", TenantChannelEndpoint.provider == "whatsapp-service", TenantChannelEndpoint.external_account_id == "edi-crm-whatsapp").first()
    assert endpoint is not None
    assert endpoint.is_active is True

def test_repeat_import_does_not_duplicate_whatsapp_endpoint_mapping(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.tenants.fetch_booking_with_invoice", fake_whatsapp_booking)
    payload = {
        "booking_id": "IMPORT-B",
        "name": "Tenant Import B",
        "first_name": "Repeat",
        "last_name": "Tenant",
        "check_in": "2026-07-03",
        "check_out": "2026-07-04",
    }
    first = client.post("/api/tenants/import", json=payload)
    second = client.post("/api/tenants/import", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "IMPORT-B").first()
    assert tenant is not None
    endpoints = db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant.id, TenantChannelEndpoint.channel_type == "whatsapp", TenantChannelEndpoint.provider == "whatsapp-service", TenantChannelEndpoint.external_account_id == "edi-crm-whatsapp").all()
    assert len(endpoints) == 1

def test_delete_imported_tenant_removes_whatsapp_endpoint_mapping(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.tenants.fetch_booking_with_invoice", fake_whatsapp_booking)
    response = client.post("/api/tenants/import", json={
        "booking_id": "IMPORT-C",
        "name": "Tenant Import C",
        "first_name": "Delete",
        "last_name": "Tenant",
        "check_in": "2026-07-05",
        "check_out": "2026-07-06",
    })
    assert response.status_code == 200
    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "IMPORT-C").first()
    assert tenant is not None
    delete_response = client.delete(f"/api/tenants/{tenant.id}")
    assert delete_response.status_code == 204
    assert db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant.id).count() == 0


def test_list_tenants_picks_latest_across_whatsapp_and_email_per_tenant(db_session):
    # Regression test for the list_tenants N+1 fix: computing last_message_date/channel used to
    # run two extra queries per tenant. This exercises the replacement bulk window-function
    # queries against multiple tenants with a mix of WhatsApp and email activity, to confirm the
    # per-tenant "most recent across both channels" result is unchanged.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    tenant_whatsapp_latest = create_tenant(db_session, name="Tenant WhatsApp Latest", booking_id="LIST-A")
    db_session.add(Communication(
        tenant_id=tenant_whatsapp_latest.id, channel="whatsapp", direction="inbound",
        provider="whatsapp-service", message="older whatsapp", created_at=base,
    ))
    db_session.add(Communication(
        tenant_id=tenant_whatsapp_latest.id, channel="whatsapp", direction="outbound",
        provider="whatsapp-service", message="newest whatsapp", created_at=base + timedelta(days=2),
    ))
    conversation_a = Conversation(provider="gmail", provider_thread_id="thread-a", tenant_id=tenant_whatsapp_latest.id, subject="s")
    db_session.add(conversation_a)
    db_session.commit()
    db_session.refresh(conversation_a)
    db_session.add(TenantConversationLink(tenant_id=tenant_whatsapp_latest.id, conversation_id=conversation_a.id))
    db_session.commit()
    db_session.add(ConversationMessage(
        conversation_id=conversation_a.id, provider="gmail", provider_message_id="msg-a-1",
        direction="inbound", body="older email", sent_at=base + timedelta(days=1),
    ))

    tenant_email_latest = create_tenant(db_session, name="Tenant Email Latest", booking_id="LIST-B")
    db_session.add(Communication(
        tenant_id=tenant_email_latest.id, channel="whatsapp", direction="inbound",
        provider="whatsapp-service", message="older whatsapp", created_at=base,
    ))
    conversation_b = Conversation(provider="gmail", provider_thread_id="thread-b", tenant_id=tenant_email_latest.id, subject="s")
    db_session.add(conversation_b)
    db_session.commit()
    db_session.refresh(conversation_b)
    db_session.add(TenantConversationLink(tenant_id=tenant_email_latest.id, conversation_id=conversation_b.id))
    db_session.commit()
    db_session.add(ConversationMessage(
        conversation_id=conversation_b.id, provider="gmail", provider_message_id="msg-b-1",
        direction="outbound", body="newest email", sent_at=base + timedelta(days=3),
    ))

    tenant_no_activity = create_tenant(db_session, name="Tenant No Activity", booking_id="LIST-C")
    db_session.commit()

    # sort_by_message's final ordering step is untouched by this fix and separately hits a
    # naive/aware datetime mismatch under the SQLite test DB (Postgres round-trips
    # DateTime(timezone=True) as aware; SQLite doesn't) — out of scope here, so this exercises
    # sort_by_message=False to isolate the per-tenant bulk-query correctness this test targets.
    result = list_tenants(db=db_session, current_user=None, sort_by_message=False, sort_desc=True)
    by_id = {tenant.id: tenant for tenant in result}

    assert by_id[tenant_whatsapp_latest.id].last_message_channel == "whatsapp"
    assert by_id[tenant_whatsapp_latest.id].last_message_direction == "outbound"
    assert by_id[tenant_whatsapp_latest.id].last_message_date.replace(tzinfo=timezone.utc) == base + timedelta(days=2)

    assert by_id[tenant_email_latest.id].last_message_channel == "email"
    assert by_id[tenant_email_latest.id].last_message_direction == "outbound"
    assert by_id[tenant_email_latest.id].last_message_date.replace(tzinfo=timezone.utc) == base + timedelta(days=3)

    assert by_id[tenant_no_activity.id].last_message_date is None


async def fake_update_booking_notes_success(booking_id, notes):
    return None


async def fake_update_booking_notes_failure(booking_id, notes):
    from fastapi import HTTPException, status
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Beds24 upstream error (500)")


def test_update_tenant_notes_syncs_to_beds24(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.tenants.update_booking_notes", fake_update_booking_notes_success)
    tenant = create_tenant(db_session, name="Tenant Notes A", booking_id="NOTES-A")

    response = client.patch(f"/api/tenants/{tenant.id}/notes", json={"notes": "Guest requested late checkout"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["notes"] == "Guest requested late checkout"
    assert payload["beds24_synced"] is True
    db_session.refresh(tenant)
    assert tenant.notes == "Guest requested late checkout"


def test_update_tenant_notes_saves_locally_when_beds24_sync_fails(client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.tenants.update_booking_notes", fake_update_booking_notes_failure)
    tenant = create_tenant(db_session, name="Tenant Notes B", booking_id="NOTES-B")

    response = client.patch(f"/api/tenants/{tenant.id}/notes", json={"notes": "Left a key with neighbor"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["notes"] == "Left a key with neighbor"
    assert payload["beds24_synced"] is False
    assert "beds24_error" in payload
    db_session.refresh(tenant)
    assert tenant.notes == "Left a key with neighbor"


def test_update_tenant_notes_returns_404_for_missing_tenant(client, monkeypatch):
    monkeypatch.setattr("app.api.tenants.update_booking_notes", fake_update_booking_notes_success)

    response = client.patch("/api/tenants/999999/notes", json={"notes": "x"})

    assert response.status_code == 404


def test_update_tenant_draft_notes_persists_without_touching_beds24(non_admin_client, db_session):
    tenant = create_tenant(db_session, name="Tenant Draft A", booking_id="DRAFT-A")

    response = non_admin_client.patch(f"/api/tenants/{tenant.id}/notes/draft", json={"draft_notes": "typing a note..."})

    assert response.status_code == 200
    assert response.json()["draft_notes"] == "typing a note..."
    db_session.refresh(tenant)
    assert tenant.draft_notes == "typing a note..."
    assert tenant.notes is None


def test_delete_tenant_draft_notes_clears_draft(non_admin_client, db_session):
    tenant = create_tenant(db_session, name="Tenant Draft B", booking_id="DRAFT-B")
    non_admin_client.patch(f"/api/tenants/{tenant.id}/notes/draft", json={"draft_notes": "abandoned edit"})

    response = non_admin_client.delete(f"/api/tenants/{tenant.id}/notes/draft")

    assert response.status_code == 200
    assert response.json()["draft_notes"] is None
    db_session.refresh(tenant)
    assert tenant.draft_notes is None


def test_update_tenant_draft_notes_returns_404_for_missing_tenant(non_admin_client):
    response = non_admin_client.patch("/api/tenants/999999/notes/draft", json={"draft_notes": "x"})

    assert response.status_code == 404


def test_saving_notes_clears_existing_draft(non_admin_client, db_session, monkeypatch):
    monkeypatch.setattr("app.api.tenants.update_booking_notes", fake_update_booking_notes_success)
    tenant = create_tenant(db_session, name="Tenant Draft C", booking_id="DRAFT-C")
    non_admin_client.patch(f"/api/tenants/{tenant.id}/notes/draft", json={"draft_notes": "half-typed note"})

    response = non_admin_client.patch(f"/api/tenants/{tenant.id}/notes", json={"notes": "Final committed note"})

    assert response.status_code == 200
    db_session.refresh(tenant)
    assert tenant.notes == "Final committed note"
    assert tenant.draft_notes is None


def test_list_tenants_includes_draft_notes_for_warning_badge(db_session):
    tenant = create_tenant(db_session, name="Tenant Draft D", booking_id="DRAFT-D")
    tenant.draft_notes = "unsaved elsewhere"
    db_session.commit()

    results = list_tenants(db=db_session, current_user=None, sort_by_message=False, sort_desc=True)

    by_id = {t.id: t for t in results}
    assert by_id[tenant.id].draft_notes == "unsaved elsewhere"


def test_webhook_extracts_notes_key_from_beds24_payload():
    from app.api.tenants import _extract_guest_fields

    fields = _extract_guest_fields({"notes": "Direct beds24 notes field", "comments": "fallback comments"})

    assert fields["notes"] == "Direct beds24 notes field"


def test_webhook_does_not_leak_guest_correspondence_into_notes():
    from app.api.tenants import _extract_guest_fields

    fields = _extract_guest_fields({
        "comments": "quoted email from guest",
        "comment": "another log entry",
        "note": "yet another",
        "message": "guest correspondence text",
    })

    assert fields["notes"] is None


def test_manual_notes_edit_records_history_with_actor(non_admin_client, db_session, monkeypatch):
    from conftest import NON_ADMIN_USER
    from app.models.tenant_notes_history import TenantNotesHistory

    monkeypatch.setattr("app.api.tenants.update_booking_notes", fake_update_booking_notes_success)
    tenant = create_tenant(db_session, name="Tenant Notes History A", booking_id="NOTES-HIST-A")

    response = non_admin_client.patch(f"/api/tenants/{tenant.id}/notes", json={"notes": "Guest wants extra towels"})

    assert response.status_code == 200
    history = db_session.query(TenantNotesHistory).filter(TenantNotesHistory.tenant_id == tenant.id).all()
    assert len(history) == 1
    assert history[0].old_value is None
    assert history[0].new_value == "Guest wants extra towels"
    assert history[0].source == "manual"
    assert history[0].changed_by_user_id == NON_ADMIN_USER.id


def test_set_tenant_notes_skips_history_row_when_value_unchanged(db_session):
    from app.models.tenant_notes_history import TenantNotesHistory
    from app.services.tenant_notes_history import set_tenant_notes

    tenant = create_tenant(db_session, name="Tenant Notes History B", booking_id="NOTES-HIST-B")
    set_tenant_notes(db_session, tenant, "Beds24 sourced note", source="beds24_webhook")
    db_session.commit()

    set_tenant_notes(db_session, tenant, "Beds24 sourced note", source="beds24_webhook")
    db_session.commit()

    history = db_session.query(TenantNotesHistory).filter(TenantNotesHistory.tenant_id == tenant.id).all()
    assert len(history) == 1
    assert tenant.notes == "Beds24 sourced note"


def test_beds24_webhook_notes_sync_records_history_with_beds24_source(client, db_session, monkeypatch):
    from app.models.tenant_notes_history import TenantNotesHistory

    async def fake_booking_fetch(booking_id):
        return {
            "id": booking_id,
            "roomName": "Studio 1",
            "firstName": "Hist",
            "lastName": "Ory",
            "arrival": "2026-08-01",
            "departure": "2026-08-05",
            "notes": "Pasted from a guest email by reception",
            "invoiceItems": [],
        }

    monkeypatch.setattr("app.api.beds24_webhooks.fetch_booking_with_invoice", fake_booking_fetch)

    response = client.get("/api/webhooks/beds24", params={"bookid": "NOTES-HIST-WEBHOOK", "status": "modify"})
    assert response.status_code == 200

    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "NOTES-HIST-WEBHOOK").first()
    assert tenant is not None
    assert tenant.notes == "Pasted from a guest email by reception"

    history = db_session.query(TenantNotesHistory).filter(TenantNotesHistory.tenant_id == tenant.id).all()
    assert len(history) == 1
    assert history[0].old_value is None
    assert history[0].new_value == "Pasted from a guest email by reception"
    assert history[0].source == "beds24_webhook"
    assert history[0].changed_by_user_id is None

    # A repeated webhook ping with the same Beds24 notes value must not add a duplicate row.
    response_again = client.get("/api/webhooks/beds24", params={"bookid": "NOTES-HIST-WEBHOOK", "status": "modify"})
    assert response_again.status_code == 200
    history_after = db_session.query(TenantNotesHistory).filter(TenantNotesHistory.tenant_id == tenant.id).all()
    assert len(history_after) == 1


def test_import_tenant_leaves_notes_empty_when_not_provided(non_admin_client, db_session, monkeypatch):
    """The import request payload is the sole source of notes on import - even if the
    underlying Beds24 booking has a populated notes property (e.g. staff pasted email
    text into it), the import must not silently pull that in behind the user's back."""
    from app.models.tenant_notes_history import TenantNotesHistory

    async def fake_booking_with_notes(booking_id):
        return {
            "id": booking_id,
            "roomName": "Studio 1",
            "arrival": "2026-07-01",
            "departure": "2026-07-02",
            "notes": "Booking notes on the Beds24 side that were never confirmed by the importer",
            "invoiceItems": [],
        }

    monkeypatch.setattr("app.api.tenants.fetch_booking_with_invoice", fake_booking_with_notes)

    response = non_admin_client.post("/api/tenants/import", json={
        "booking_id": "IMPORT-NOTES-EMPTY",
        "name": "Tenant Import Notes",
        "first_name": "Import",
        "last_name": "Notes",
        "check_in": "2026-07-01",
        "check_out": "2026-07-02",
    })

    assert response.status_code == 200
    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "IMPORT-NOTES-EMPTY").first()
    assert tenant is not None
    assert tenant.notes is None
    assert db_session.query(TenantNotesHistory).filter(TenantNotesHistory.tenant_id == tenant.id).count() == 0


def test_import_tenant_saves_explicitly_confirmed_notes(non_admin_client, db_session, monkeypatch):
    from conftest import NON_ADMIN_USER
    from app.models.tenant_notes_history import TenantNotesHistory

    monkeypatch.setattr("app.api.tenants.fetch_booking_with_invoice", fake_whatsapp_booking)

    response = non_admin_client.post("/api/tenants/import", json={
        "booking_id": "IMPORT-NOTES-CONFIRMED",
        "name": "Tenant Import Confirmed",
        "first_name": "Import",
        "last_name": "Confirmed",
        "check_in": "2026-07-01",
        "check_out": "2026-07-02",
        "notes": "Reviewed and confirmed by staff during import",
    })

    assert response.status_code == 200
    tenant = db_session.query(Tenant).filter(Tenant.booking_id == "IMPORT-NOTES-CONFIRMED").first()
    assert tenant is not None
    assert tenant.notes == "Reviewed and confirmed by staff during import"
    history = db_session.query(TenantNotesHistory).filter(TenantNotesHistory.tenant_id == tenant.id).all()
    assert len(history) == 1
    assert history[0].old_value is None
    assert history[0].new_value == "Reviewed and confirmed by staff during import"
    assert history[0].source == "beds24_import"
    assert history[0].changed_by_user_id == NON_ADMIN_USER.id


def test_notes_history_endpoint_returns_entries_newest_first(non_admin_client, db_session, monkeypatch):
    from conftest import NON_ADMIN_USER

    monkeypatch.setattr("app.api.tenants.update_booking_notes", fake_update_booking_notes_success)
    tenant = create_tenant(db_session, name="Tenant Notes History C", booking_id="NOTES-HIST-C")
    if db_session.query(User).filter(User.id == NON_ADMIN_USER.id).first() is None:
        db_session.add(User(id=NON_ADMIN_USER.id, email=NON_ADMIN_USER.email, password_hash="x", is_active=True, is_admin=False))
        db_session.commit()

    non_admin_client.patch(f"/api/tenants/{tenant.id}/notes", json={"notes": "First note"})
    non_admin_client.patch(f"/api/tenants/{tenant.id}/notes", json={"notes": "Second note"})

    response = non_admin_client.get(f"/api/tenants/{tenant.id}/notes/history")

    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 2
    assert entries[0]["new_value"] == "Second note"
    assert entries[0]["old_value"] == "First note"
    assert entries[0]["source"] == "manual"
    assert entries[0]["changed_by_email"] == "member@example.com"
    assert entries[1]["new_value"] == "First note"


def test_list_tenants_filters_by_last_message_direction(db_session):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    tenant_inbound = create_tenant(db_session, name="Tenant Inbound", booking_id="DIR-A")
    db_session.add(Communication(
        tenant_id=tenant_inbound.id, channel="whatsapp", direction="inbound",
        provider="whatsapp-service", message="hello", created_at=base,
    ))

    tenant_outbound = create_tenant(db_session, name="Tenant Outbound", booking_id="DIR-B")
    db_session.add(Communication(
        tenant_id=tenant_outbound.id, channel="whatsapp", direction="outbound",
        provider="whatsapp-service", message="hi back", created_at=base,
    ))

    tenant_no_activity = create_tenant(db_session, name="Tenant No Activity", booking_id="DIR-C")
    db_session.commit()

    inbound_result = list_tenants(
        db=db_session, current_user=None, last_message_direction="inbound",
        sort_by_message=False, sort_desc=True,
    )
    inbound_ids = {tenant.id for tenant in inbound_result}
    assert inbound_ids == {tenant_inbound.id}

    outbound_result = list_tenants(
        db=db_session, current_user=None, last_message_direction="outbound",
        sort_by_message=False, sort_desc=True,
    )
    outbound_ids = {tenant.id for tenant in outbound_result}
    assert outbound_ids == {tenant_outbound.id}

    assert tenant_no_activity.id not in inbound_ids
    assert tenant_no_activity.id not in outbound_ids


def test_list_tenants_filters_by_multiple_statuses(db_session):
    tenant_enquiry = create_tenant(db_session, name="Tenant Enquiry", booking_id="STATUS-A")
    tenant_enquiry.booking_status = "Enquiry"

    tenant_request = create_tenant(db_session, name="Tenant Request", booking_id="STATUS-B")
    tenant_request.booking_status = "Request"

    tenant_confirmed = create_tenant(db_session, name="Tenant Confirmed", booking_id="STATUS-C")
    tenant_confirmed.booking_status = "Confirmed"
    db_session.commit()

    result = list_tenants(
        db=db_session, current_user=None, status=["Enquiry", "Request"], status_filter=True,
        sort_by_message=False, sort_desc=True,
    )
    result_ids = {tenant.id for tenant in result}
    assert result_ids == {tenant_enquiry.id, tenant_request.id}
    assert tenant_confirmed.id not in result_ids


def test_list_tenants_empty_status_filter_shows_nothing(db_session):
    create_tenant(db_session, name="Tenant Confirmed", booking_id="STATUS-D")

    result = list_tenants(
        db=db_session, current_user=None, status=[], status_filter=True,
        sort_by_message=False, sort_desc=True,
    )
    assert result == []


def test_list_tenant_statuses_returns_distinct_values_from_data(db_session):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="STATUS-E")
    tenant_a.booking_status = "confirmed"

    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="STATUS-F")
    tenant_b.booking_status = "confirmed"

    tenant_c = create_tenant(db_session, name="Tenant C", booking_id="STATUS-G")
    tenant_c.booking_status = "Custom Status"

    create_tenant(db_session, name="Tenant No Status", booking_id="STATUS-H")
    db_session.commit()

    statuses = list_tenant_statuses(db=db_session, current_user=None)
    assert statuses == ["Custom Status", "confirmed"]


def test_list_tenants_computes_unread_count_per_user(db_session):
    tenant = create_tenant(db_session, name="Tenant Unread", booking_id="UNREAD-1")
    other_tenant = create_tenant(db_session, name="Tenant Unread Other", booking_id="UNREAD-2")

    user = User(email="unread-test@example.com", password_hash="x", is_active=True, is_admin=False)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    notification_one = Notification(tenant_id=tenant.id, tenant_name=tenant.name, channel="whatsapp", direction="inbound")
    notification_two = Notification(tenant_id=tenant.id, tenant_name=tenant.name, channel="whatsapp", direction="inbound")
    notification_other = Notification(tenant_id=other_tenant.id, tenant_name=other_tenant.name, channel="whatsapp", direction="inbound")
    db_session.add_all([notification_one, notification_two, notification_other])
    db_session.commit()
    db_session.refresh(notification_one)
    db_session.refresh(notification_two)
    db_session.refresh(notification_other)

    result = list_tenants(db=db_session, current_user=user, sort_by_message=False, sort_desc=True)
    by_id = {t.id: t for t in result}
    assert by_id[tenant.id].unread_count == 2
    assert by_id[other_tenant.id].unread_count == 1

    db_session.add(NotificationReadState(notification_id=notification_one.id, user_id=user.id))
    db_session.commit()

    result_after_read = list_tenants(db=db_session, current_user=user, sort_by_message=False, sort_desc=True)
    by_id_after_read = {t.id: t for t in result_after_read}
    assert by_id_after_read[tenant.id].unread_count == 1


def test_list_tenants_unread_count_defaults_to_zero_without_current_user(db_session):
    tenant = create_tenant(db_session, name="Tenant No User", booking_id="UNREAD-3")
    db_session.add(Notification(tenant_id=tenant.id, tenant_name=tenant.name, channel="whatsapp", direction="inbound"))
    db_session.commit()

    result = list_tenants(db=db_session, current_user=None, sort_by_message=False, sort_desc=True)
    by_id = {t.id: t for t in result}
    assert by_id[tenant.id].unread_count == 0
