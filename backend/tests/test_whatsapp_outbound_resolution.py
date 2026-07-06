from app.models.communication import Communication
from app.models.tenant import Tenant


def create_tenant(db_session, name='Tenant A', booking_id='B-1'):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_whatsapp_communication(db_session, tenant_id, provider_message_id=None, whatsapp_chat_id=None, external_account_id=None):
    communication = Communication(
        tenant_id=tenant_id,
        channel='whatsapp',
        direction='outbound',
        provider='whatsapp-service',
        provider_message_id=provider_message_id,
        whatsapp_chat_id=whatsapp_chat_id,
        external_account_id=external_account_id,
        message='Hello',
    )
    db_session.add(communication)
    db_session.commit()
    db_session.refresh(communication)
    return communication


def test_whatsapp_outbound_resolution_by_message_id(client, db_session):
    tenant = create_tenant(db_session, name='Tenant Resolve A', booking_id='RES-A')
    communication = create_whatsapp_communication(
        db_session,
        tenant.id,
        provider_message_id='msg-tenant-resolve-a',
        whatsapp_chat_id='155066153590862@lid',
        external_account_id='client-a',
    )

    response = client.get('/api/communications/whatsapp/outbound-resolution', params={'provider_message_id': 'msg-tenant-resolve-a'})

    assert response.status_code == 200
    payload = response.json()
    assert payload['found'] is True
    assert payload['tenant_id'] == tenant.id
    assert payload['communication_id'] == communication.id
    assert payload['resolution_strategy'] == 'provider_message_id'


def test_whatsapp_outbound_resolution_by_chat_and_account(client, db_session):
    tenant = create_tenant(db_session, name='Tenant Resolve B', booking_id='RES-B')
    communication = create_whatsapp_communication(
        db_session,
        tenant.id,
        whatsapp_chat_id='155066153590862@lid',
        external_account_id='client-b',
    )

    response = client.get(
        '/api/communications/whatsapp/outbound-resolution',
        params={'whatsapp_chat_id': '155066153590862@lid', 'external_account_id': 'client-b'},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['found'] is True
    assert payload['tenant_id'] == tenant.id
    assert payload['communication_id'] == communication.id
    assert payload['resolution_strategy'] == 'chat_id_external_account_id'


def test_whatsapp_outbound_resolution_returns_unresolved_when_no_match(client):
    response = client.get(
        '/api/communications/whatsapp/outbound-resolution',
        params={'provider_message_id': 'missing-message', 'whatsapp_chat_id': '155066153590862@lid', 'external_account_id': 'client-missing'},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['found'] is False
    assert payload['resolution_strategy'] == 'unresolved'
