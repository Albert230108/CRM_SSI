from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app.api.tenants import list_tenants
from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint


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

def test_create_tenant_creates_whatsapp_endpoint_mapping(client, db_session):
    response = client.post('/api/tenants', json={'booking_id': 'CREATE-A', 'name': 'Tenant Create A'})
    assert response.status_code == 201
    payload = response.json()
    assert payload["booking_id"] == "CREATE-A"
    endpoint = db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == payload["id"], TenantChannelEndpoint.channel_type == "whatsapp", TenantChannelEndpoint.provider == "whatsapp-service", TenantChannelEndpoint.external_account_id == "edi-crm-whatsapp").first()
    assert endpoint is not None
    assert endpoint.is_active is True

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
