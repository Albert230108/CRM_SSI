from app.core.quotation_token import decode_quotation_token
from app.models.tenant import Tenant


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_mint_quotation_token_returns_url_and_valid_token(non_admin_client, db_session, monkeypatch):
    import app.api.quotation as quotation_module
    monkeypatch.setattr(quotation_module, "QUOTATION_MANAGER_URL", "https://quotations.example.com")

    tenant = create_tenant(db_session, name="Quote Tenant", booking_id="QUOTE-1")

    response = non_admin_client.post(f"/api/tenants/{tenant.id}/quotation-token")

    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert "expires_at" in body
    assert body["quotation_url"] == f"https://quotations.example.com?token={body['token']}"

    payload = decode_quotation_token(body["token"])
    assert payload.tenant_id == tenant.id
    assert payload.booking_id == "QUOTE-1"
    assert payload.scope == "quotation"


def test_mint_quotation_token_requires_login():
    # A fresh TestClient with no dependency overrides - get_current_user should reject
    # a request with no Authorization header at all.
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as unauthenticated_client:
        response = unauthenticated_client.post("/api/tenants/1/quotation-token")

    assert response.status_code == 401


def test_mint_quotation_token_for_missing_tenant_returns_404(non_admin_client, monkeypatch):
    import app.api.quotation as quotation_module
    monkeypatch.setattr(quotation_module, "QUOTATION_MANAGER_URL", "https://quotations.example.com")

    response = non_admin_client.post("/api/tenants/999999/quotation-token")

    assert response.status_code == 404


def test_mint_quotation_token_without_configured_url_returns_503(non_admin_client, db_session, monkeypatch):
    import app.api.quotation as quotation_module
    monkeypatch.setattr(quotation_module, "QUOTATION_MANAGER_URL", "")

    tenant = create_tenant(db_session, name="Quote Tenant 3", booking_id="QUOTE-3")

    response = non_admin_client.post(f"/api/tenants/{tenant.id}/quotation-token")

    assert response.status_code == 503
