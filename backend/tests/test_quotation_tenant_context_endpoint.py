from app.core.quotation_token import create_quotation_token
from app.models.tenant import Tenant
from tests.conftest import ADMIN_USER


def _headers(tenant_id, booking_id="CTX-1"):
    token = create_quotation_token(tenant_id=tenant_id, booking_id=booking_id, issued_by_user_id=ADMIN_USER.id)
    return {"Authorization": f"Bearer {token}"}


def test_tenant_context_endpoint_returns_tenant_for_matching_token(client, db_session):
    tenant = Tenant(booking_id="CTX-1", name="Context Tenant", room_name="Studio 1")
    db_session.add(tenant)
    db_session.commit()

    response = client.get(f"/api/quotation/tenant-context/{tenant.id}", headers=_headers(tenant.id))

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant.id
    assert body["booking_id"] == "CTX-1"


def test_tenant_context_endpoint_rejects_mismatched_tenant_id(client, db_session):
    tenant_a = Tenant(booking_id="CTX-A", name="Tenant A")
    tenant_b = Tenant(booking_id="CTX-B", name="Tenant B")
    db_session.add_all([tenant_a, tenant_b])
    db_session.commit()

    # A token minted for tenant_a must not be usable to read tenant_b's context.
    response = client.get(f"/api/quotation/tenant-context/{tenant_b.id}", headers=_headers(tenant_a.id, "CTX-A"))

    assert response.status_code == 403


def test_tenant_context_endpoint_rejects_tenant_less_token(client, db_session):
    # The nav bar's "Quotations" button mints a token scoped to no tenant at all
    # (see POST /api/quotation/token) - it must never be able to read a tenant's
    # context, only search/browse bookings.
    tenant = Tenant(booking_id="CTX-1", name="Context Tenant")
    db_session.add(tenant)
    db_session.commit()

    headers = _headers(None, None)
    response = client.get(f"/api/quotation/tenant-context/{tenant.id}", headers=headers)

    assert response.status_code == 403


def test_tenant_context_endpoint_requires_token(client, db_session):
    tenant = Tenant(booking_id="CTX-1", name="Context Tenant")
    db_session.add(tenant)
    db_session.commit()

    response = client.get(f"/api/quotation/tenant-context/{tenant.id}")

    assert response.status_code == 401
