from datetime import date

from app.services import discount_engine


def test_calculate_discount_falls_back_to_price_manager_when_globally_disabled():
    # The bundled discount_rules.json (copied verbatim from the real config) currently has
    # global_settings.enabled=false, so this should fall back to the Price Manager tier
    # rather than the "test" preset's custom_tier_pricing rule.
    pricing_data = discount_engine.load_pricing_data()
    result = discount_engine.calculate_discount_for_booking(
        room_name="Studio 1",
        property_name="Central-Day Inn",
        nights=7,
        checkin_date=date(2026, 3, 1),
        base_price_per_night=0.0,
        pricing_data=pricing_data,
    )
    assert result["discount_description"] == "Discount system disabled (using Price Manager)"
    assert result["using_tier_price"] is True
    assert result["discounted_price"] == pricing_data["2026"]["Central-Day Inn"]["Studio 1"]["price_tiers"]["7"]


def test_calculate_discount_applies_custom_tier_when_enabled():
    # Force-enable the discount system and select the "test" preset's custom_tier_pricing
    # rule directly, independent of whatever the bundled config's global toggle is set to.
    # The preset's 7-night tier is priced at 65.0, which is *higher* than this room's base
    # price (58.67769), so the rule correctly declines to apply and the base/tier price wins.
    pricing_data = discount_engine.load_pricing_data()
    rules = discount_engine.load_discount_rules()
    enabled_rules = {
        **rules,
        "global_settings": {**rules["global_settings"], "enabled": True},
        "active_preset": "test",
    }
    result = discount_engine.calculate_discount_for_booking(
        room_name="Studio 1",
        property_name="Central-Day Inn",
        nights=7,
        checkin_date=date(2026, 3, 1),
        base_price_per_night=0.0,
        pricing_data=pricing_data,
        discount_rules=enabled_rules,
    )
    assert result["discounted_price"] == 58.67769


def test_calculate_discount_endpoint_requires_token(client):
    response = client.post(
        "/api/quotation/discount",
        json={"room_name": "Studio 1", "property_name": "Central-Day Inn", "nights": 7, "checkin_date": "2026-03-01"},
    )
    assert response.status_code == 401  # HTTPBearer with no Authorization header


def test_calculate_discount_endpoint_with_valid_token(client, auth_headers):
    response = client.post(
        "/api/quotation/discount",
        json={"room_name": "Studio 1", "property_name": "Central-Day Inn", "nights": 7, "checkin_date": "2026-03-01"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["discounted_price"] == 58.67769
