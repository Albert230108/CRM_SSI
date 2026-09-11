from app.models.tenant import Tenant
from tests.conftest import ADMIN_USER


async def fake_update_booking_invoice_items(booking_id, original_invoice_item_ids, final_invoice_items, booking_fields=None):
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


def test_send_invoice_items_forwards_payment_status_to_beds24(client, db_session, monkeypatch):
    captured = {}

    async def capturing_update(booking_id, original_invoice_item_ids, final_invoice_items, booking_fields=None):
        captured["final_invoice_items"] = final_invoice_items
        captured["booking_fields"] = booking_fields

    import app.api.quotation as quotation_module

    monkeypatch.setattr(quotation_module, "update_booking_invoice_items", capturing_update)
    monkeypatch.setattr(quotation_module, "sync_tenant_from_beds24_booking", fake_sync)

    tenant = Tenant(booking_id="INV-3", name="Existing Tenant")
    db_session.add(tenant)
    db_session.commit()

    headers = _auth_headers_for(tenant.id, "INV-3")
    response = client.post(
        "/api/quotation/beds24-booking/INV-3/invoice-items",
        json={
            "all_original_invoice_item_ids": [],
            "invoice_items": [
                {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vat_rate": 9},
                {"type": "payment", "description": "Installment 1", "qty": 1, "amount": 100.0, "status": "12-Sep-2026"},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200
    items = captured["final_invoice_items"]
    charge_item, payment_item = items
    # Charges have no meaningful Beds24 payment status - key stays absent, not null.
    assert "status" not in charge_item
    assert payment_item["status"] == "12-Sep-2026"
    # C2: positive payments get Beds24's pay-link tag appended on send.
    assert payment_item["description"] == "Installment 1 [PAYLINK: 100.00]"
    # D1: booking_fields are forwarded (all None here since no status/sub-status/flag was sent).
    assert captured["booking_fields"] == {"status": None, "subStatus": None, "flagText": None}
