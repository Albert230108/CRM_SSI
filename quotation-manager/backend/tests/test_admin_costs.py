from app.services import admin_costs


def test_calculate_admin_costs_clamps_to_max():
    result = admin_costs.calculate_admin_costs(
        property_name="Central-Day Inn",
        total_charges=10000.0,
        deposit_amount=400.0,
        city_tax_amount=50.0,
    )
    assert result["clamped"] is True
    assert result["admin_cost"] == round(result["max_limit"], 2)


def test_calculate_admin_costs_unknown_property_uses_defaults():
    result = admin_costs.calculate_admin_costs(
        property_name="Some New Property",
        total_charges=100.0,
        deposit_amount=0.0,
        city_tax_amount=0.0,
    )
    assert result["percentage"] == 5.0
    assert result["property_name"] == "Some New Property"


def test_admin_costs_endpoint_with_valid_token(client, auth_headers):
    response = client.post(
        "/api/quotation/admin-costs",
        json={
            "property_name": "Central-Day Inn",
            "total_charges": 500.0,
            "deposit_amount": 400.0,
            "city_tax_amount": 20.0,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["property_name"] == "Central-Day Inn"
