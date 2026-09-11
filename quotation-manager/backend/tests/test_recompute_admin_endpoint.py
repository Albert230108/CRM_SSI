"""B3: /quotation/recompute-admin keeps the Administration costs line in sync as charges change,
status-independently. It must mirror charge_builder's admin step: base = ex-VAT sum of non-admin
charges minus pass-through city tax (and any security-deposit line), grossed up by check-in VAT."""


def _item(description, qty, amount, vat_rate, type="charge"):
    return {"type": type, "description": description, "qty": qty, "amount": amount, "vat_rate": vat_rate}


def test_recompute_admin_matches_net_base_and_grosses_up(client, auth_headers):
    # 100.00 incl @21% -> net 82.6446...; admin base excludes the admin line and the city tax.
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
    # Admin excl is a % of the net rent (city tax excluded), clamped; incl = excl grossed up 21%.
    assert body["admin_cost_excl"] > 0
    assert round(body["admin_cost_incl"], 2) == round(body["admin_cost_excl"] * 1.21, 2)


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
