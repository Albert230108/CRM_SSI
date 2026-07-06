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
