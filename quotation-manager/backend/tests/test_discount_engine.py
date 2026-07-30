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


def test_calculate_discount_uses_longest_qualifying_tier():
    # Regression test: the Price Manager's real tier keys are 7/14/30/60/90, not the
    # hardcoded 56/28/7 the code used to check. Before the fix, a 30-night stay would
    # silently fall back to the 7-night price instead of the (cheaper) 30-night tier.
    pricing_data = discount_engine.load_pricing_data()
    tiers_2026 = pricing_data["2026"]["Central-Day Inn"]["Studio 1"]["price_tiers"]
    for nights, tier_key in [(30, "30"), (60, "60"), (90, "90")]:
        result = discount_engine.calculate_discount_for_booking(
            room_name="Studio 1",
            property_name="Central-Day Inn",
            nights=nights,
            checkin_date=date(2026, 3, 1),
            base_price_per_night=0.0,
            pricing_data=pricing_data,
        )
        assert result["discounted_price"] == tiers_2026[tier_key]
        assert result["discounted_price"] != tiers_2026["7"]


def test_calculate_discount_keeps_seven_night_tier_for_short_stays():
    # Guards the shortest-tier fallback: a stay that doesn't qualify for any tier's
    # minimum should still be priced off the shortest defined tier, same as before.
    pricing_data = discount_engine.load_pricing_data()
    tiers_2026 = pricing_data["2026"]["Central-Day Inn"]["Studio 1"]["price_tiers"]
    result = discount_engine.calculate_discount_for_booking(
        room_name="Studio 1",
        property_name="Central-Day Inn",
        nights=5,
        checkin_date=date(2026, 3, 1),
        base_price_per_night=0.0,
        pricing_data=pricing_data,
    )
    assert result["discounted_price"] == tiers_2026["7"]


def test_calculate_discount_dispatches_dynamic_rule_type():
    # Regression test: calculate_dynamic_discount was defined but never wired into the
    # rule-type dispatch chain, so any "dynamic" rule silently no-op'd (fell through
    # to "Unknown rule type" and was dropped). Force-enable a dynamic rule directly,
    # independent of the bundled config's global toggle.
    pricing_data = discount_engine.load_pricing_data()
    rules = discount_engine.load_discount_rules()
    dynamic_rules = {
        **rules,
        "global_settings": {**rules["global_settings"], "enabled": True},
        "active_preset": "dynamic_test",
        "presets": {
            "dynamic_test": {
                "name": "Dynamic test",
                "enabled": True,
                "rules": [
                    {
                        "id": "dynamic_rule",
                        "type": "dynamic",
                        "name": "Dynamic market rate",
                        "active": True,
                        "priority": 5,
                        "applies_to": {"properties": ["all"], "rooms": ["all"]},
                        "conditions": {"min_nights": 1},
                        "config": {"comparison_tier": "7", "min_percentage_below": 5.0},
                    }
                ],
            }
        },
    }
    # Studio 1's base price (58.67769, from base_prices.json) is ~10% below the
    # 2025 7-night tier (65.13761), so the dynamic rule should fire.
    result = discount_engine.calculate_discount_for_booking(
        room_name="Studio 1",
        property_name="Central-Day Inn",
        nights=7,
        checkin_date=date(2025, 6, 1),
        base_price_per_night=0.0,
        pricing_data=pricing_data,
        discount_rules=dynamic_rules,
    )
    assert result["rule_type"] == "dynamic"
    assert "Market discount" in result["discount_manager_description"]


def test_tier_based_price_discount_honours_explicit_tier_keys():
    # The configurable tier_keys path (used when a rule explicitly lists which tiers
    # to check) must be unaffected by the default-tier-key fix.
    price_tiers = {"7": 65.0, "30": 50.0}
    price, description = discount_engine.calculate_tier_based_price_discount(
        nights=30,
        base_price=60.0,
        price_tiers=price_tiers,
        tier_config={"tier_keys": [30, 7]},
    )
    assert price == 50.0
    assert "30-night tier" in description


def test_calculate_discount_endpoint_returns_long_stay_tier(client, auth_headers):
    response = client.post(
        "/api/quotation/discount",
        json={"room_name": "Studio 1", "property_name": "Central-Day Inn", "nights": 30, "checkin_date": "2026-03-01"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    pricing_data = discount_engine.load_pricing_data()
    assert response.json()["discounted_price"] == pricing_data["2026"]["Central-Day Inn"]["Studio 1"]["price_tiers"]["30"]


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
