from datetime import date

import pytest

from app.services import admin_costs as admin_costs_service
from app.services import charge_builder
from app.services import pricing_config
from app.services import vat


def _sum_line_total_net(charges, kind=None):
    return round(sum(c["qty"] * c["amount_excl_vat"] for c in charges if kind is None or c["kind"] == kind), 2)


def _room(pricing_data, prop, room):
    return pricing_data[prop]["rooms"][room]


def _tier(pricing_data, prop, room, iso_date, nights):
    rng = pricing_config.resolve_range(_room(pricing_data, prop, room), date.fromisoformat(iso_date))
    return pricing_config.select_tier_price(rng["price_tiers"], nights)


def _extra(pricing_data, prop):
    return pricing_data[prop]["extra_services"]


def test_build_charges_entirely_in_2025():
    pricing_data = pricing_config.load_pricing_data()

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2025, 6, 1),
        checkout_date=date(2025, 6, 8),
        adults=1,
        pricing_data=pricing_data,
    )

    assert result["nights"] == 7
    assert result["total_guests"] == 1

    accommodation = [c for c in result["charges"] if c["kind"] == "accommodation"]
    assert len(accommodation) == 1
    assert accommodation[0]["vat_rate"] == 9
    assert accommodation[0]["qty"] == 7
    expected_rate = _tier(pricing_data, "Central-Day Inn", "Studio 1", "2025-06-01", 7)
    assert accommodation[0]["amount"] == vat.gross_amount(expected_rate, 9)
    assert accommodation[0]["amount_excl_vat"] == round(expected_rate, 2)

    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert len(city_tax) == 1
    assert city_tax[0]["qty"] == 7
    assert city_tax[0]["amount"] == round(_extra(pricing_data, "Central-Day Inn")["city_tax"], 2)
    assert city_tax[0]["vat_rate"] == 0

    end_cleaning = [c for c in result["charges"] if c["kind"] == "end_cleaning"]
    assert len(end_cleaning) == 1
    assert end_cleaning[0]["amount_excl_vat"] == round(_room(pricing_data, "Central-Day Inn", "Studio 1")["end_cleaning"], 2)
    assert end_cleaning[0]["amount"] == vat.gross_amount(end_cleaning[0]["amount_excl_vat"], 9)
    assert end_cleaning[0]["vat_rate"] == 9

    admin = [c for c in result["charges"] if c["kind"] == "admin_costs"]
    assert len(admin) == 1 and admin[0]["vat_rate"] == 9
    assert not [c for c in result["charges"] if c["kind"] == "extra_person"]


def test_build_charges_entirely_in_2026():
    pricing_data = pricing_config.load_pricing_data()

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2026, 3, 1), checkout_date=date(2026, 3, 8), adults=1, pricing_data=pricing_data,
    )

    accommodation = [c for c in result["charges"] if c["kind"] == "accommodation"]
    assert len(accommodation) == 1 and accommodation[0]["vat_rate"] == 21
    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert city_tax[0]["amount"] == round(_extra(pricing_data, "Central-Day Inn")["city_tax"], 2)
    admin = [c for c in result["charges"] if c["kind"] == "admin_costs"]
    assert admin[0]["vat_rate"] == 21


def test_build_charges_splits_at_range_and_vat_boundary():
    """A stay spanning the 2025->2026 range boundary (which coincides with the VAT boundary)
    splits into two accommodation segments, each priced from its own range's tier."""
    pricing_data = pricing_config.load_pricing_data()

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2025, 12, 28), checkout_date=date(2026, 1, 5), adults=1, pricing_data=pricing_data,
    )

    assert result["nights"] == 8
    accommodation = [c for c in result["charges"] if c["kind"] == "accommodation"]
    assert len(accommodation) == 2
    pre_2026, from_2026 = accommodation
    # 8-night stay selects the highest tier <= 8, i.e. the 7-night tier, in each range.
    assert pre_2026["vat_rate"] == 9 and pre_2026["qty"] == 4
    assert pre_2026["amount"] == vat.gross_amount(_tier(pricing_data, "Central-Day Inn", "Studio 1", "2025-12-28", 8), 9)
    assert from_2026["vat_rate"] == 21 and from_2026["qty"] == 4
    assert from_2026["amount"] == vat.gross_amount(_tier(pricing_data, "Central-Day Inn", "Studio 1", "2026-01-01", 8), 21)


def test_build_charges_selects_higher_night_tier_for_long_stay():
    """A 30-night stay is priced from the 30-night tier, not the 7-night rack rate."""
    pricing_data = pricing_config.load_pricing_data()
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2026, 3, 1), checkout_date=date(2026, 3, 31), adults=1, pricing_data=pricing_data,
    )
    assert result["nights"] == 30
    accommodation = [c for c in result["charges"] if c["kind"] == "accommodation"][0]
    assert accommodation["amount_excl_vat"] == round(_tier(pricing_data, "Central-Day Inn", "Studio 1", "2026-03-01", 30), 2)
    # No separate discount row any more - the tier itself is the long-stay price.
    assert not [c for c in result["charges"] if c["kind"] == "long_stay_discount"]


def test_build_charges_ssi_flag_uses_municipality_cost():
    pricing_data = pricing_config.load_pricing_data()
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2025, 6, 1), checkout_date=date(2025, 6, 8), adults=1,
        quotation_flag="(SSI)", pricing_data=pricing_data,
    )
    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert "Municipality Cost" in city_tax[0]["description"]
    assert city_tax[0]["amount"] == round(_extra(pricing_data, "Central-Day Inn")["municipality_cost"], 2)


def test_build_charges_default_flag_uses_city_tax():
    pricing_data = pricing_config.load_pricing_data()
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2025, 6, 1), checkout_date=date(2025, 6, 8), adults=1, pricing_data=pricing_data,
    )
    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert "Citytax" in city_tax[0]["description"]
    assert city_tax[0]["amount"] == round(_extra(pricing_data, "Central-Day Inn")["city_tax"], 2)


def test_build_charges_skips_zero_municipality_cost():
    pricing_data = pricing_config.load_pricing_data()
    assert _extra(pricing_data, "Blekerstraat")["municipality_cost"] == 0.0
    result = charge_builder.build_standard_charges(
        property_name="Blekerstraat", room_name="House",
        checkin_date=date(2025, 6, 1), checkout_date=date(2025, 6, 8), adults=1,
        quotation_flag="(SSI)", pricing_data=pricing_data,
    )
    assert not [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert any("skipped" in note for note in result["notes"])


def test_build_charges_adds_extra_person_row_for_multiple_guests():
    pricing_data = pricing_config.load_pricing_data()
    extra_person_cost = _room(pricing_data, "Central-Day Inn", "Studio 1")["extra_person_cost"]
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2026, 3, 1), checkout_date=date(2026, 3, 8), adults=2, children=1, pricing_data=pricing_data,
    )
    extra_person = [c for c in result["charges"] if c["kind"] == "extra_person"]
    assert len(extra_person) == 1
    assert extra_person[0]["qty"] == 7 * 2
    assert extra_person[0]["amount"] == vat.gross_amount(extra_person_cost, 21)


def test_build_charges_admin_row_matches_admin_costs_service():
    pricing_data = pricing_config.load_pricing_data()
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2025, 6, 1), checkout_date=date(2025, 6, 8), adults=1, pricing_data=pricing_data,
    )
    non_admin_charges = [c for c in result["charges"] if c["kind"] != "admin_costs"]
    admin_row = next(c for c in result["charges"] if c["kind"] == "admin_costs")
    expected = admin_costs_service.calculate_admin_costs(
        property_name="Central-Day Inn",
        total_charges=_sum_line_total_net(non_admin_charges),
        deposit_amount=0.0,
        city_tax_amount=_sum_line_total_net(non_admin_charges, kind="city_tax"),
    )
    assert admin_row["amount_excl_vat"] == expected["admin_cost"]


def test_build_charges_rejects_inverted_dates():
    with pytest.raises(charge_builder.ChargeBuilderError):
        charge_builder.build_standard_charges(
            property_name="Central-Day Inn", room_name="Studio 1",
            checkin_date=date(2026, 3, 8), checkout_date=date(2026, 3, 1),
        )


def test_build_charges_rejects_unknown_room():
    with pytest.raises(charge_builder.ChargeBuilderError):
        charge_builder.build_standard_charges(
            property_name="Central-Day Inn", room_name="Nonexistent Room",
            checkin_date=date(2026, 3, 1), checkout_date=date(2026, 3, 8),
        )


def test_build_charges_endpoint_requires_token(client):
    response = client.post(
        "/api/quotation/build-charges",
        json={"property_name": "Central-Day Inn", "room_name": "Studio 1", "check_in": "2026-03-01", "check_out": "2026-03-08"},
    )
    assert response.status_code == 401


def test_build_charges_endpoint_with_valid_token(client, auth_headers):
    response = client.post(
        "/api/quotation/build-charges",
        json={"property_name": "Central-Day Inn", "room_name": "Studio 1", "check_in": "2026-03-01", "check_out": "2026-03-08", "adults": 1},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["nights"] == 7 and body["total_guests"] == 1
    assert any(c["kind"] == "accommodation" for c in body["charges"])


def test_build_charges_endpoint_rejects_unknown_room(client, auth_headers):
    response = client.post(
        "/api/quotation/build-charges",
        json={"property_name": "Central-Day Inn", "room_name": "Nonexistent Room", "check_in": "2026-03-01", "check_out": "2026-03-08"},
        headers=auth_headers,
    )
    assert response.status_code == 400
