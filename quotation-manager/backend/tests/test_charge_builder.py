from datetime import date

import pytest

from app.services import admin_costs as admin_costs_service
from app.services import charge_builder
from app.services import pricing_config
from app.services import vat


def _sum_line_total_net(charges, kind=None):
    return round(sum(c["qty"] * c["amount_excl_vat"] for c in charges if kind is None or c["kind"] == kind), 2)


def _sum_gross(charges, kind=None):
    return round(sum(c["qty"] * c["amount"] for c in charges if kind is None or c["kind"] == kind), 2)


def _one(charges, kind):
    rows = [c for c in charges if c["kind"] == kind]
    assert len(rows) == 1, f"expected exactly one {kind} row, got {len(rows)}"
    return rows[0]


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


def test_build_charges_long_stay_prices_at_rack_rate_with_discount_line():
    """Desktop-exact: a 30-night stay is priced at the range's shortest (rack) rate, with a
    negative Long Stay Discount line bringing it down to the selected tier (strict '>': 30
    nights -> the '14' tier)."""
    pricing_data = pricing_config.load_pricing_data()
    checkin, checkout = date(2026, 3, 1), date(2026, 3, 31)
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=checkin, checkout_date=checkout, adults=1, pricing_data=pricing_data,
    )
    assert result["nights"] == 30

    rng = pricing_config.resolve_range(_room(pricing_data, "Central-Day Inn", "Studio 1"), checkin)
    base_rate = pricing_config.shortest_tier_price(rng["price_tiers"])
    tier_rate = pricing_config.select_tier_price(rng["price_tiers"], 30)
    assert tier_rate < base_rate  # the 30-night stay really does get a cheaper tier

    accommodation = _one(result["charges"], "accommodation")
    assert accommodation["amount_excl_vat"] == round(base_rate, 2)
    assert accommodation["amount"] == vat.gross_amount(base_rate, 21)

    discount = _one(result["charges"], "long_stay_discount")
    assert discount["description"] == "Long Stay Discount (30 nights)"
    assert discount["qty"] == 30
    assert discount["vat_rate"] == 21
    assert discount["amount"] == vat.gross_amount(tier_rate - base_rate, 21)
    assert discount["amount"] < 0

    # Net accommodation after the discount equals the selected tier price.
    net_per_night = accommodation["amount_excl_vat"] + discount["amount_excl_vat"]
    assert net_per_night == round(tier_rate - base_rate + base_rate, 2) == round(tier_rate, 2)


def test_build_charges_short_stay_has_no_discount_line():
    """A 7-night stay sits at the rack rate already, so no discount row is emitted."""
    pricing_data = pricing_config.load_pricing_data()
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2026, 3, 1), checkout_date=date(2026, 3, 8), adults=1, pricing_data=pricing_data,
    )
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


def test_build_charges_emits_zero_municipality_cost_row():
    """Desktop-exact: a €0 municipality cost still yields a 0.00 row (no silent skip)."""
    pricing_data = pricing_config.load_pricing_data()
    assert _extra(pricing_data, "Blekerstraat")["municipality_cost"] == 0.0
    result = charge_builder.build_standard_charges(
        property_name="Blekerstraat", room_name="House",
        checkin_date=date(2025, 6, 1), checkout_date=date(2025, 6, 8), adults=1,
        quotation_flag="(SSI)", pricing_data=pricing_data,
    )
    city_tax = _one(result["charges"], "city_tax")
    assert "Municipality Cost" in city_tax["description"]
    assert city_tax["amount"] == 0.0
    assert city_tax["vat_rate"] == 0


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


def test_build_charges_admin_row_uses_gross_base_and_double_grosses():
    """Desktop-exact admin math: base = running VAT-INCLUSIVE total minus the Citytax line;
    the clamped ex-VAT result is grossed up AGAIN by the check-in VAT rate."""
    pricing_data = pricing_config.load_pricing_data()
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2025, 6, 1), checkout_date=date(2025, 6, 8), adults=1, pricing_data=pricing_data,
    )
    non_admin_charges = [c for c in result["charges"] if c["kind"] != "admin_costs"]
    admin_row = _one(result["charges"], "admin_costs")
    expected = admin_costs_service.calculate_admin_costs(
        property_name="Central-Day Inn",
        total_charges=_sum_gross(non_admin_charges),            # VAT-inclusive base
        deposit_amount=0.0,
        city_tax_amount=_sum_gross(non_admin_charges, kind="city_tax"),
    )
    assert admin_row["amount_excl_vat"] == expected["admin_cost"]
    assert admin_row["vat_rate"] == 9
    assert admin_row["amount"] == round(expected["admin_cost"] * 1.09, 2)  # grossed again


def test_build_charges_admin_base_keeps_municipality_cost():
    """The admin base subtracts only 'Citytax', never 'Municipality Cost', so an (SSI) booking's
    admin fee is computed on a higher base than the equivalent citytax booking."""
    pricing_data = pricing_config.load_pricing_data()
    kwargs = dict(property_name="Central-Day Inn", room_name="Studio 1",
                  checkin_date=date(2026, 3, 1), checkout_date=date(2026, 3, 20),
                  adults=1, pricing_data=pricing_data)
    citytax = charge_builder.build_standard_charges(**kwargs)
    municipality = charge_builder.build_standard_charges(quotation_flag="(SSI)", **kwargs)
    assert _one(municipality["charges"], "admin_costs")["amount_excl_vat"] >= \
        _one(citytax["charges"], "admin_costs")["amount_excl_vat"]


# --- Worked-example acceptance test (reproduces the desktop reference exactly) ---

WORKED_EXAMPLE_PRICING = {
    "Ensche-Day Inn": {
        "extra_services": {"city_tax": 3.39, "municipality_cost": 2.0, "deposit": 400.0},
        "rooms": {
            "Room 2": {
                "end_cleaning": 73.55372,
                "extra_person_cost": 3.71901,
                "price_ranges": [
                    {"start": "2026-01-01", "end": "2026-12-31",
                     "price_tiers": {"7": 65.28926, "14": 61.15702, "30": 57.02479,
                                     "60": 52.89256, "90": 48.76033}},
                ],
            }
        },
    }
}


def test_build_charges_worked_example_matches_desktop_reference():
    """Ensche-Day Inn / Room 2, 2026-02-01 -> 2026-03-03 (30 nights), 2 adults, 8% admin
    (95.04132-219.00826). Must reproduce the reference table exactly, incl. Administration
    costs = €236.58."""
    result = charge_builder.build_standard_charges(
        property_name="Ensche-Day Inn", room_name="Room 2",
        checkin_date=date(2026, 2, 1), checkout_date=date(2026, 3, 3),
        adults=2, children=0, pricing_data=WORKED_EXAMPLE_PRICING,
    )
    charges = result["charges"]
    assert result["nights"] == 30

    accommodation = _one(charges, "accommodation")
    assert accommodation["qty"] == 30 and accommodation["amount"] == 79.00 and accommodation["vat_rate"] == 21
    assert _sum_gross([accommodation]) == 2370.00

    discount = _one(charges, "long_stay_discount")
    assert discount["qty"] == 30 and discount["amount"] == -5.00 and discount["vat_rate"] == 21
    assert _sum_gross([discount]) == -150.00

    city_tax = _one(charges, "city_tax")
    assert city_tax["qty"] == 60 and city_tax["amount"] == 3.39 and city_tax["vat_rate"] == 0
    assert _sum_gross([city_tax]) == 203.40

    extra = _one(charges, "extra_person")
    assert extra["qty"] == 30 and extra["amount"] == 4.50 and extra["vat_rate"] == 21
    assert _sum_gross([extra]) == 135.00

    cleaning = _one(charges, "end_cleaning")
    assert cleaning["amount"] == 89.00 and cleaning["vat_rate"] == 21

    admin = _one(charges, "admin_costs")
    assert admin["vat_rate"] == 21
    assert admin["amount"] == 236.58


def test_build_charges_long_stay_zero_vat_single_period():
    """>183 nights within a single VAT period -> accommodation (and discount) at 0% VAT, with a
    '(excl. VAT)' description suffix (desktop single-period rule)."""
    result = charge_builder.build_standard_charges(
        property_name="Ensche-Day Inn", room_name="Room 2",
        checkin_date=date(2026, 1, 1), checkout_date=date(2026, 8, 1),  # 212 nights, all 2026
        adults=1, pricing_data=WORKED_EXAMPLE_PRICING,
    )
    assert result["nights"] == 212
    accommodation = _one(result["charges"], "accommodation")
    assert accommodation["vat_rate"] == 0
    assert "(excl. VAT)" in accommodation["description"]
    # The discount row follows the accommodation VAT (also 0%).
    discount = _one(result["charges"], "long_stay_discount")
    assert discount["vat_rate"] == 0


def test_build_charges_long_stay_spanning_keeps_per_segment_vat():
    """A >183-night stay that crosses 2026-01-01 still bills per-segment 9%/21% (no 0% VAT) -
    the desktop applied 0% only in its single-period branch."""
    result = charge_builder.build_standard_charges(
        property_name="Ensche-Day Inn", room_name="Room 2",
        checkin_date=date(2025, 10, 1), checkout_date=date(2026, 6, 1),  # ~243 nights, spans VAT
        adults=1,
        pricing_data={
            "Ensche-Day Inn": {
                "extra_services": {"city_tax": 3.39, "municipality_cost": 2.0, "deposit": 400.0},
                "rooms": {"Room 2": {
                    "end_cleaning": 73.55372, "extra_person_cost": 3.71901,
                    "price_ranges": [
                        {"start": "2025-01-01", "end": "2025-12-31",
                         "price_tiers": {"7": 62.38532, "90": 39.66973}},
                        {"start": "2026-01-01", "end": "2026-12-31",
                         "price_tiers": {"7": 65.28926, "90": 48.76033}},
                    ],
                }},
            }
        },
    )
    accommodation = [c for c in result["charges"] if c["kind"] == "accommodation"]
    assert {c["vat_rate"] for c in accommodation} == {9, 21}
    assert all("(excl. VAT)" not in c["description"] for c in accommodation)


def test_build_charges_extra_person_per_segment_vat_on_spanning_stay():
    """Extra-person charge splits per VAT segment (9% for 2025 nights, 21% for 2026)."""
    result = charge_builder.build_standard_charges(
        property_name="Ensche-Day Inn", room_name="Room 2",
        checkin_date=date(2025, 12, 28), checkout_date=date(2026, 1, 5), adults=2,
        pricing_data={
            "Ensche-Day Inn": {
                "extra_services": {"city_tax": 3.39, "municipality_cost": 2.0, "deposit": 400.0},
                "rooms": {"Room 2": {
                    "end_cleaning": 73.55372, "extra_person_cost": 3.71901,
                    "price_ranges": [
                        {"start": "2025-01-01", "end": "2025-12-31", "price_tiers": {"7": 62.38532}},
                        {"start": "2026-01-01", "end": "2026-12-31", "price_tiers": {"7": 65.28926}},
                    ],
                }},
            }
        },
    )
    extra = [c for c in result["charges"] if c["kind"] == "extra_person"]
    assert len(extra) == 2
    by_vat = {c["vat_rate"]: c for c in extra}
    assert set(by_vat) == {9, 21}
    assert by_vat[9]["qty"] == 4 and by_vat[21]["qty"] == 4  # 4 nights each side x 1 extra person
    # City tax also splits per segment.
    city_tax = [c for c in result["charges"] if c["kind"] == "city_tax"]
    assert len(city_tax) == 2
    assert all("to" in c["description"] for c in city_tax)  # dated label on spanning citytax rows


def test_build_charges_emits_zero_extra_person_row():
    """Desktop-exact: with >1 guest, an extra-person row is emitted even at a €0 rate."""
    result = charge_builder.build_standard_charges(
        property_name="Ensche-Day Inn", room_name="Room 2",
        checkin_date=date(2026, 3, 1), checkout_date=date(2026, 3, 8), adults=2,
        pricing_data={
            "Ensche-Day Inn": {
                "extra_services": {"city_tax": 3.39, "municipality_cost": 2.0, "deposit": 400.0},
                "rooms": {"Room 2": {
                    "end_cleaning": 73.55372, "extra_person_cost": 0.0,
                    "price_ranges": [{"start": "2026-01-01", "end": "2026-12-31", "price_tiers": {"7": 65.0}}],
                }},
            }
        },
    )
    extra = _one(result["charges"], "extra_person")
    assert extra["amount"] == 0.0 and extra["qty"] == 7


@pytest.mark.parametrize("flag", ["(SSI)", "SSI", " (ssi) ", "(Ssi)"])
def test_build_charges_flag_normalization_selects_municipality(flag):
    pricing_data = pricing_config.load_pricing_data()
    result = charge_builder.build_standard_charges(
        property_name="Central-Day Inn", room_name="Studio 1",
        checkin_date=date(2026, 3, 1), checkout_date=date(2026, 3, 8), adults=1,
        quotation_flag=flag, pricing_data=pricing_data,
    )
    assert "Municipality Cost" in _one(result["charges"], "city_tax")["description"]


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
