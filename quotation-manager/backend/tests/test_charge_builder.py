from datetime import date

import pytest

from app.services import admin_costs as admin_costs_service
from app.services import charge_builder
from app.services import discount_engine


def _sum_line_total(charges, kind=None):
    return round(sum(c["qty"] * c["amount"] for c in charges if kind is None or c["kind"] == kind), 2)


def test_build_charges_entirely_in_2025():
    pricing_data = discount_engine.load_pricing_data()
    tiers = pricing_data["2025"]["Central-Day Inn"]["Studio 1"]["price_tiers"]
    extra_services = pricing_data["2025"]["Central-Day Inn"]["extra_services"]

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
    assert accommodation[0]["amount"] == round(tiers["7"], 2)

    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert len(city_tax) == 1
    assert city_tax[0]["qty"] == 7
    assert city_tax[0]["amount"] == round(extra_services["city_tax"], 2)
    assert city_tax[0]["vat_rate"] == 0

    end_cleaning = [c for c in result["charges"] if c["kind"] == "end_cleaning"]
    assert len(end_cleaning) == 1
    assert end_cleaning[0]["amount"] == round(pricing_data["2025"]["Central-Day Inn"]["Studio 1"]["end_cleaning"], 2)
    assert end_cleaning[0]["vat_rate"] == 9

    admin = [c for c in result["charges"] if c["kind"] == "admin_costs"]
    assert len(admin) == 1
    assert admin[0]["vat_rate"] == 9

    assert not [c for c in result["charges"] if c["kind"] == "extra_person"]


def test_build_charges_entirely_in_2026():
    pricing_data = discount_engine.load_pricing_data()
    extra_services = pricing_data["2026"]["Central-Day Inn"]["extra_services"]

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2026, 3, 1),
        checkout_date=date(2026, 3, 8),
        adults=1,
        pricing_data=pricing_data,
    )

    accommodation = [c for c in result["charges"] if c["kind"] == "accommodation"]
    assert len(accommodation) == 1
    assert accommodation[0]["vat_rate"] == 21

    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert city_tax[0]["amount"] == round(extra_services["city_tax"], 2)
    assert city_tax[0]["vat_rate"] == 0

    end_cleaning = [c for c in result["charges"] if c["kind"] == "end_cleaning"]
    assert end_cleaning[0]["vat_rate"] == 21

    admin = [c for c in result["charges"] if c["kind"] == "admin_costs"]
    assert admin[0]["vat_rate"] == 21


def test_build_charges_spans_2026_vat_boundary():
    pricing_data = discount_engine.load_pricing_data()

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2025, 12, 28),
        checkout_date=date(2026, 1, 5),
        adults=1,
        pricing_data=pricing_data,
    )

    assert result["nights"] == 8

    accommodation = [c for c in result["charges"] if c["kind"] == "accommodation"]
    assert len(accommodation) == 2
    pre_2026, from_2026 = accommodation
    assert pre_2026["vat_rate"] == 9
    assert pre_2026["qty"] == 4
    assert pre_2026["amount"] == round(pricing_data["2025"]["Central-Day Inn"]["Studio 1"]["price_tiers"]["7"], 2)
    assert from_2026["vat_rate"] == 21
    assert from_2026["qty"] == 4
    assert from_2026["amount"] == round(pricing_data["2026"]["Central-Day Inn"]["Studio 1"]["price_tiers"]["7"], 2)

    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert len(city_tax) == 1
    assert city_tax[0]["qty"] == 8  # 8 nights x 1 guest, one row governed by check-in year

    # Check-in year (2025) governs cleaning/admin VAT for the whole booking.
    end_cleaning = [c for c in result["charges"] if c["kind"] == "end_cleaning"]
    admin = [c for c in result["charges"] if c["kind"] == "admin_costs"]
    assert end_cleaning[0]["vat_rate"] == 9
    assert admin[0]["vat_rate"] == 9


def test_build_charges_long_stay_adds_discount_row():
    pricing_data = discount_engine.load_pricing_data()
    tiers = pricing_data["2026"]["Central-Day Inn"]["Studio 1"]["price_tiers"]

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2026, 3, 1),
        checkout_date=date(2026, 3, 31),  # 30 nights
        adults=1,
        pricing_data=pricing_data,
    )

    assert result["nights"] == 30
    discount_rows = [c for c in result["charges"] if c["kind"] == "long_stay_discount"]
    assert len(discount_rows) == 1
    assert discount_rows[0]["amount"] < 0

    accommodation = [c for c in result["charges"] if c["kind"] == "accommodation"][0]
    effective_price = accommodation["amount"] + discount_rows[0]["amount"]
    # Two rows are each independently rounded to cents, so allow a small tolerance.
    assert effective_price == pytest.approx(tiers["30"], abs=0.02)


def test_build_charges_short_stay_has_no_discount_row():
    pricing_data = discount_engine.load_pricing_data()

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2026, 3, 1),
        checkout_date=date(2026, 3, 8),  # 7 nights: same as the rack-rate tier itself
        adults=1,
        pricing_data=pricing_data,
    )

    assert not [c for c in result["charges"] if c["kind"] == "long_stay_discount"]
    assert any("No long-stay discount" in note for note in result["notes"])


def test_build_charges_ssi_flag_uses_municipality_cost():
    pricing_data = discount_engine.load_pricing_data()
    extra_services = pricing_data["2025"]["Central-Day Inn"]["extra_services"]

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2025, 6, 1),
        checkout_date=date(2025, 6, 8),
        adults=1,
        quotation_flag="(SSI)",
        pricing_data=pricing_data,
    )

    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert len(city_tax) == 1
    assert "Municipality Cost" in city_tax[0]["description"]
    assert city_tax[0]["amount"] == round(extra_services["municipality_cost"], 2)
    assert city_tax[0]["vat_rate"] == 0


def test_build_charges_default_flag_uses_city_tax():
    pricing_data = discount_engine.load_pricing_data()
    extra_services = pricing_data["2025"]["Central-Day Inn"]["extra_services"]

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2025, 6, 1),
        checkout_date=date(2025, 6, 8),
        adults=1,
        pricing_data=pricing_data,
    )

    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert "Citytax" in city_tax[0]["description"]
    assert city_tax[0]["amount"] == round(extra_services["city_tax"], 2)


def test_build_charges_skips_zero_municipality_cost():
    pricing_data = discount_engine.load_pricing_data()
    assert pricing_data["2025"]["Blekerstraat"]["extra_services"]["municipality_cost"] == 0.0

    result = charge_builder.build_standard_charges(
        property_name="Blekerstraat",
        room_name="House",
        checkin_date=date(2025, 6, 1),
        checkout_date=date(2025, 6, 8),
        adults=1,
        quotation_flag="(SSI)",
        pricing_data=pricing_data,
    )

    assert not [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert any("skipped" in note for note in result["notes"])


def test_build_charges_adds_extra_person_row_for_multiple_guests():
    pricing_data = discount_engine.load_pricing_data()
    extra_person_cost = pricing_data["2026"]["Central-Day Inn"]["Studio 1"]["extra_person_cost"]

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2026, 3, 1),
        checkout_date=date(2026, 3, 8),
        adults=2,
        children=1,
        pricing_data=pricing_data,
    )

    assert result["total_guests"] == 3
    extra_person = [c for c in result["charges"] if c["kind"] == "extra_person"]
    assert len(extra_person) == 1
    assert extra_person[0]["qty"] == 7 * 2  # nights x (total_guests - 1)
    assert extra_person[0]["amount"] == round(extra_person_cost, 2)


def test_build_charges_skips_extra_person_row_when_rate_is_zero():
    pricing_data = discount_engine.load_pricing_data()
    assert pricing_data["2025"]["Central-Day Inn"]["Studio 2"]["extra_person_cost"] == 0.0

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 2",
        checkin_date=date(2025, 6, 1),
        checkout_date=date(2025, 6, 8),
        adults=2,
        pricing_data=pricing_data,
    )

    assert not [c for c in result["charges"] if c["kind"] == "extra_person"]
    assert any("Extra person charge skipped" in note for note in result["notes"])


def test_build_charges_admin_row_matches_admin_costs_service():
    pricing_data = discount_engine.load_pricing_data()

    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn",
        room_name="Studio 1",
        checkin_date=date(2025, 6, 1),
        checkout_date=date(2025, 6, 8),
        adults=1,
        pricing_data=pricing_data,
    )

    non_admin_charges = [c for c in result["charges"] if c["kind"] != "admin_costs"]
    admin_row = next(c for c in result["charges"] if c["kind"] == "admin_costs")

    expected = admin_costs_service.calculate_admin_costs(
        property_name="Central-Day Inn",
        total_charges=_sum_line_total(non_admin_charges),
        deposit_amount=0.0,
        city_tax_amount=_sum_line_total(non_admin_charges, kind="city_tax"),
    )
    assert admin_row["amount"] == expected["admin_cost"]


def test_build_charges_rejects_inverted_dates():
    with pytest.raises(charge_builder.ChargeBuilderError):
        charge_builder.build_standard_charges(
            property_name="Central-Day Inn",
            room_name="Studio 1",
            checkin_date=date(2026, 3, 8),
            checkout_date=date(2026, 3, 1),
        )


def test_build_charges_rejects_unknown_room():
    with pytest.raises(charge_builder.ChargeBuilderError):
        charge_builder.build_standard_charges(
            property_name="Central-Day Inn",
            room_name="Nonexistent Room",
            checkin_date=date(2026, 3, 1),
            checkout_date=date(2026, 3, 8),
        )


def test_build_charges_endpoint_requires_token(client):
    response = client.post(
        "/api/quotation/build-charges",
        json={
            "property_name": "Central-Day Inn",
            "room_name": "Studio 1",
            "check_in": "2026-03-01",
            "check_out": "2026-03-08",
        },
    )
    assert response.status_code == 401


def test_build_charges_endpoint_with_valid_token(client, auth_headers):
    response = client.post(
        "/api/quotation/build-charges",
        json={
            "property_name": "Central-Day Inn",
            "room_name": "Studio 1",
            "check_in": "2026-03-01",
            "check_out": "2026-03-08",
            "adults": 1,
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["nights"] == 7
    assert body["total_guests"] == 1
    assert any(c["kind"] == "accommodation" for c in body["charges"])


def test_build_charges_endpoint_rejects_inverted_dates(client, auth_headers):
    response = client.post(
        "/api/quotation/build-charges",
        json={
            "property_name": "Central-Day Inn",
            "room_name": "Studio 1",
            "check_in": "2026-03-08",
            "check_out": "2026-03-01",
        },
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_build_charges_endpoint_rejects_unknown_room(client, auth_headers):
    response = client.post(
        "/api/quotation/build-charges",
        json={
            "property_name": "Central-Day Inn",
            "room_name": "Nonexistent Room",
            "check_in": "2026-03-01",
            "check_out": "2026-03-08",
        },
        headers=auth_headers,
    )
    assert response.status_code == 400
