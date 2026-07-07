from sqlalchemy.exc import IntegrityError

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
    endpoint = db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == payload["id"], TenantChannelEndpoint.channel_type == "whatsapp", TenantChannelEndpoint.provider == "whatsapp-service", TenantChannelEndpoint.external_account_id == "swifthk-whatsapp").first()
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
    endpoint = db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant.id, TenantChannelEndpoint.channel_type == "whatsapp", TenantChannelEndpoint.provider == "whatsapp-service", TenantChannelEndpoint.external_account_id == "swifthk-whatsapp").first()
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
    endpoints = db_session.query(TenantChannelEndpoint).filter(TenantChannelEndpoint.tenant_id == tenant.id, TenantChannelEndpoint.channel_type == "whatsapp", TenantChannelEndpoint.provider == "whatsapp-service", TenantChannelEndpoint.external_account_id == "swifthk-whatsapp").all()
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
