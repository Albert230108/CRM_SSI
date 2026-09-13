"""B3: /quotation/recompute-admin keeps the Administration costs line in sync as charges change.
It must mirror charge_builder's desktop-exact admin step: base = VAT-INCLUSIVE sum of non-admin
charges minus the pass-through Citytax line (Municipality Cost is NOT subtracted) and any
security-deposit line; the clamped ex-VAT result is grossed up again by the check-in VAT rate."""

from datetime import date

from app.services import admin_costs as admin_costs_service
from app.services import charge_builder
from app.services import pricing_config


def _item(description, qty, amount, vat_rate, type="charge"):
    return {"type": type, "description": description, "qty": qty, "amount": amount, "vat_rate": vat_rate}


def test_recompute_admin_uses_gross_base_and_grosses_up(client, auth_headers):
    # Amounts on the form are VAT-inclusive. Base = gross total minus the citytax line; the admin
    # line is ignored as a base input; result is grossed again by 21%.
    payload = {
        "property_name": "Central-Day Inn",
        "check_in": "2026-07-01",
        "invoice_items": [
            _item("Rent for Studio 1", 1, 1000.0, 21),
            _item("Citytax for 1 person(s)", 5, 3.39, 0),
            _item("Administration costs", 1, 999.0, 21),  # stale; must be ignored as a base input
        ],
    }
    response = client.post("/api/quotation/recompute-admin", json=payload, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["vat_rate"] == 21.0
    # Gross base = 1000.00 (citytax 5x3.39 subtracted); expected matches the admin-cost service.
    expected = admin_costs_service.calculate_admin_costs(
        property_name="Central-Day Inn", total_charges=1000.0 + 5 * 3.39,
        deposit_amount=0.0, city_tax_amount=round(5 * 3.39, 2),
    )
    assert body["admin_cost_excl"] == expected["admin_cost"]
    assert round(body["admin_cost_incl"], 2) == round(expected["admin_cost"] * 1.21, 2)


def test_recompute_admin_keeps_municipality_in_base(client, auth_headers):
    """Municipality Cost is NOT subtracted from the base (unlike Citytax)."""
    with_municipality = client.post(
        "/api/quotation/recompute-admin",
        json={"property_name": "Central-Day Inn", "check_in": "2026-07-01", "invoice_items": [
            _item("Rent", 1, 1000.0, 21),
            _item("Municipality Cost (registration)", 10, 2.0, 0),
        ]},
        headers=auth_headers,
    ).json()
    rent_only = client.post(
        "/api/quotation/recompute-admin",
        json={"property_name": "Central-Day Inn", "check_in": "2026-07-01", "invoice_items": [
            _item("Rent", 1, 1000.0, 21),
        ]},
        headers=auth_headers,
    ).json()
    # The €20 municipality line lifted the base, so admin is higher (unless both hit the clamp).
    assert with_municipality["admin_cost_excl"] >= rent_only["admin_cost_excl"]


def test_recompute_admin_matches_build_charges_admin(client, auth_headers):
    """Parity: recompute-admin over the exact rows build_standard_charges produced returns the
    same Administration costs figure as the build-charges admin row."""
    pricing_data = pricing_config.load_pricing_data()
    built = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2026, 3, 1),
        checkout_date=date(2026, 3, 25),
        adults=2, pricing_data=pricing_data,
    )
    admin_row = next(c for c in built["charges"] if c["kind"] == "admin_costs")
    invoice_items = [
        _item(c["description"], c["qty"], c["amount"], c["vat_rate"])
        for c in built["charges"] if c["kind"] != "admin_costs"
    ]
    body = client.post(
        "/api/quotation/recompute-admin",
        json={"property_name": "Central-Day Inn", "check_in": "2026-03-01", "invoice_items": invoice_items},
        headers=auth_headers,
    ).json()
    assert round(body["admin_cost_incl"], 2) == round(admin_row["amount"], 2)


def test_recompute_admin_ignores_stale_admin_line_value(client, auth_headers):
    """A huge stale admin amount must not inflate the recomputed base."""
    base = [_item("Rent", 1, 500.0, 21)]
    small = client.post(
        "/api/quotation/recompute-admin",
        json={"property_name": "Central-Day Inn", "check_in": "2026-07-01", "invoice_items": base},
        headers=auth_headers,
    ).json()
    with_stale = client.post(
        "/api/quotation/recompute-admin",
        json={
            "property_name": "Central-Day Inn",
            "check_in": "2026-07-01",
            "invoice_items": base + [_item("Administration costs", 1, 9999.0, 21)],
        },
        headers=auth_headers,
    ).json()
    assert small["admin_cost_excl"] == with_stale["admin_cost_excl"]
