from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.tenant_channel_resolver import resolve_tenant_for_inbound_channel


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_duplicate_endpoint_prevention(client, db_session):
    tenant = create_tenant(db_session)
    payload = {
        "tenant_id": tenant.id,
        "channel_type": "whatsapp",
        "provider": "whatsapp-service",
        "external_account_id": "client-1",
        "webhook_token": "token-1",
    }
    r1 = client.post("/api/admin/tenant-channel-endpoints", json=payload)
    assert r1.status_code == 200
    r2 = client.post("/api/admin/tenant-channel-endpoints", json=payload)
    assert r2.status_code == 400


def test_tenant_resolution_by_webhook_token(db_session):
    tenant = create_tenant(db_session, name="Tenant B", booking_id="B-2")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="client-2",
        webhook_token="route-token",
        signing_secret="secret-1",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    result = resolve_tenant_for_inbound_channel(db_session, {"webhook_token": "route-token"}, {}, {})
    assert result.tenant.id == tenant.id
    assert result.strategy == "webhook_token"


def test_tenant_resolution_by_provider_and_external_account_id(db_session):
    tenant = create_tenant(db_session, name="Tenant C", booking_id="B-3")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="client-3",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    result = resolve_tenant_for_inbound_channel(db_session, {"provider": "whatsapp-service", "external_account_id": "client-3"}, {}, {})
    assert result.tenant.id == tenant.id
    assert result.strategy == "provider_external_account_id"


def test_inactive_endpoint_ignored(db_session):
    tenant = create_tenant(db_session, name="Tenant D", booking_id="B-4")
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="client-4",
        webhook_token="route-token-4",
        is_active=False,
    )
    db_session.add(endpoint)
    db_session.commit()

    result = resolve_tenant_for_inbound_channel(db_session, {"webhook_token": "route-token-4", "provider": "whatsapp-service", "external_account_id": "client-4"}, {}, {})
    assert result.tenant is None
    assert result.strategy == "unresolved"


def test_fallback_still_works_for_unmigrated_tenants(db_session):
    tenant = create_tenant(db_session, name="Tenant E", booking_id="B-5")
    tenant.phone = "+31 6 12345678"
    db_session.commit()

    result = resolve_tenant_for_inbound_channel(db_session, {"sender": "+31612345678"}, {}, {})
    assert result.tenant.id == tenant.id
    assert result.strategy == "legacy_phone_inference"
