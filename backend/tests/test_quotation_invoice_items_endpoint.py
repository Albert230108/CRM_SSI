from app.models.tenant import Tenant
from tests.conftest import ADMIN_USER


async def fake_update_booking_invoice_items(booking_id, original_invoice_item_ids, final_invoice_items):
    return None


async def fake_sync(db, booking_id, booking=None, allow_create=True):
    tenant = db.query(Tenant).filter(Tenant.booking_id == booking_id).first()
    if tenant is None:
        tenant = Tenant(booking_id=booking_id, name="Synced Tenant")
        db.add(tenant)
        db.flush()
    return tenant


def _auth_headers_for(tenant_id, booking_id):
    from app.core.quotation_token import create_quotation_token

    token = create_quotation_token(tenant_id=tenant_id, booking_id=booking_id, issued_by_user_id=ADMIN_USER.id)
    return {"Authorization": f"Bearer {token}"}


def test_send_invoice_items_endpoint_pushes_and_resyncs(client, db_session, monkeypatch):
    import app.api.quotation as quotation_module

    monkeypatch.setattr(quotation_module, "update_booking_invoice_items", fake_update_booking_invoice_items)
    monkeypatch.setattr(quotation_module, "sync_tenant_from_beds24_booking", fake_sync)

    tenant = Tenant(booking_id="INV-1", name="Existing Tenant")
    db_session.add(tenant)
    db_session.commit()

    headers = _auth_headers_for(tenant.id, "INV-1")
    response = client.post(
        "/api/quotation/beds24-booking/INV-1/invoice-items",
        json={
            "all_original_invoice_item_ids": ["old-1"],
            "invoice_items": [
                {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant.id


def test_send_invoice_items_endpoint_requires_token(client):
    response = client.post(
        "/api/quotation/beds24-booking/INV-2/invoice-items",
        json={"all_original_invoice_item_ids": [], "invoice_items": []},
    )
    assert response.status_code == 401
