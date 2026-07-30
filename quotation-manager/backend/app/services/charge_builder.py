"""
Auto-generates the standard invoice charge-line stack for a booking, ported
from the desktop Quotation Manager's update_predefined_rows
(Python-EmailQuotation-1/src/interface.py). The web port previously had no
equivalent: the editor only loaded whatever invoiceItems already existed on
the Beds24 booking and left a human to build the rest by hand.

Builds, in order:
1. Accommodation - split across the 2026-01-01 VAT boundary (9% before, 21%
   from 2026), priced at each year's 7-night rack rate.
2. Long Stay Discount - a negative row when the (now-fixed) discount engine
   or Price Manager tiers beat that rack rate.
3. City tax, or "Municipality Cost (registration)" when quotation_flag is
   "(SSI)".
4. Extra person charge, when there's more than one guest and the room has a
   configured extra-person rate.
5. End cleaning.
6. Administration costs, via the already-ported admin_costs service, based
   on the running total of the rows above.
"""

from datetime import date, timedelta
from typing import Any, Optional

from app.services import admin_costs as admin_costs_service
from app.services import discount_engine
from app.services import pdf_service

VAT_2026_START = date(2026, 1, 1)
SSI_QUOTATION_FLAG = "(SSI)"
_DISCOUNT_ROW_EPSILON = 0.005


class ChargeBuilderError(Exception):
    """Raised when a booking can't be priced (bad dates, unknown property/room)."""


def vat_rate_for_date(d: date) -> float:
    return 21.0 if d >= VAT_2026_START else 9.0


def _year_keys(pricing_data: dict) -> list[str]:
    return sorted((key for key in pricing_data if str(key).isdigit()), key=int)


def _resolve_year_key(pricing_data: dict, year: int) -> str:
    """str(year) if that year is defined, else the closest defined year <=
    year, else the earliest defined year. Keeps a booking in an
    as-yet-undefined year (e.g. 2027, before that data is added) working off
    the latest real tiers instead of failing outright."""
    keys = _year_keys(pricing_data)
    if not keys:
        raise ChargeBuilderError("No pricing data available")

    target = str(year)
    if target in keys:
        return target

    earlier = [key for key in keys if int(key) <= year]
    return earlier[-1] if earlier else keys[0]


def _get_room_config(pricing_data: dict, year_key: str, property_name: str, room_name: str) -> dict:
    try:
        property_data = pricing_data[year_key][property_name]
    except KeyError:
        raise ChargeBuilderError(f"Unknown property: {property_name}") from None
    try:
        return property_data[room_name]
    except KeyError:
        raise ChargeBuilderError(f"Unknown room '{room_name}' for property '{property_name}'") from None


def _get_extra_services(pricing_data: dict, year_key: str, property_name: str) -> dict:
    try:
        return pricing_data[year_key][property_name]["extra_services"]
    except KeyError:
        raise ChargeBuilderError(f"Unknown property: {property_name}") from None


def _rack_rate(pricing_data: dict, year: int, property_name: str, room_name: str) -> float:
    """Undiscounted per-night list price for that year: the 7-night tier,
    falling back to base_prices.json via discount_engine.get_base_price if a
    room somehow has no 7-night tier defined."""
    year_key = _resolve_year_key(pricing_data, year)
    room_config = _get_room_config(pricing_data, year_key, property_name, room_name)
    price_tiers = room_config.get("price_tiers", {})
    if "7" in price_tiers:
        return price_tiers["7"]
    return discount_engine.get_base_price(property_name, room_name, pricing_data)


def _safe_replace_year(d: date, year: int) -> date:
    """date.replace(year=...), clamping Feb 29 to Feb 28 on a non-leap target year."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def _split_years(checkin_date: date, checkout_date: date) -> list[int]:
    """Years split_booking_by_vat will actually key its unit_price lookup by:
    checkin_date.year for the pre-2026 segment (if any), and exactly 2026
    for the 2026+ segment (if any) - the split boundary is always
    2026-01-01, regardless of how many calendar years the "before" side
    happens to span."""
    years = {checkin_date.year}
    if checkout_date > VAT_2026_START:
        years.add(2026)
    return sorted(years)


def build_standard_charges(
    property_name: str,
    room_name: str,
    checkin_date: date,
    checkout_date: date,
    adults: int = 1,
    children: int = 0,
    quotation_flag: Optional[str] = None,
    pricing_data: Optional[dict] = None,
    discount_rules: Optional[dict] = None,
) -> dict[str, Any]:
    if checkout_date <= checkin_date:
        raise ChargeBuilderError("check_out must be after check_in")

    if pricing_data is None:
        pricing_data = discount_engine.load_pricing_data()

    nights = (checkout_date - checkin_date).days
    total_guests = adults + children
    checkin_year_key = _resolve_year_key(pricing_data, checkin_date.year)
    checkin_vat = vat_rate_for_date(checkin_date)
    split_years = _split_years(checkin_date, checkout_date)

    # Fail fast on an unknown property/room rather than silently emitting zeros.
    checkin_room_config = _get_room_config(pricing_data, checkin_year_key, property_name, room_name)

    charges: list[dict[str, Any]] = []
    notes: list[str] = []

    # 1. Accommodation, split at the 2026-01-01 VAT boundary if the stay spans it.
    rack_by_year = {year: _rack_rate(pricing_data, year, property_name, room_name) for year in split_years}
    accommodation_segments = pdf_service.split_booking_by_vat(checkin_date, checkout_date, rack_by_year)
    multi_segment = len(accommodation_segments) > 1
    for segment in accommodation_segments:
        start_display = segment["start"].strftime("%d-%b-%Y")
        if multi_segment:
            end_display = (segment["end"] - timedelta(days=1)).strftime("%d-%b-%Y")
            description = f"{room_name} - {start_display} to {end_display}"
        else:
            end_display = checkout_date.strftime("%d-%b-%Y")
            description = f"{room_name} - {start_display} - {end_display}"
        charges.append({
            "kind": "accommodation",
            "description": description,
            "qty": float(segment["nights"]),
            "amount": round(segment["unit_price"], 2),
            "vat_rate": float(segment["vat"]),
            "detail": None,
        })

    # 2. Long Stay Discount. Uses the FULL stay length (not the segment
    # length) for tier qualification in every year touched - a stay
    # spanning New Year must qualify for its tier on both sides, not be
    # evaluated as two separate short stays.
    discount_delta_by_year: dict[int, float] = {}
    discount_detail_by_year: dict[int, str] = {}
    for year in split_years:
        year_checkin_date = _safe_replace_year(checkin_date, year)
        result = discount_engine.calculate_discount_for_booking(
            room_name=room_name,
            property_name=property_name,
            nights=nights,
            checkin_date=year_checkin_date,
            base_price_per_night=0.0,
            pricing_data=pricing_data,
            discount_rules=discount_rules,
        )
        discount_delta_by_year[year] = min(0.0, result["discounted_price"] - rack_by_year[year])
        discount_detail_by_year[year] = result["discount_description"]

    if any(delta < -_DISCOUNT_ROW_EPSILON for delta in discount_delta_by_year.values()):
        discount_segments = pdf_service.split_booking_by_vat(checkin_date, checkout_date, discount_delta_by_year)
        for segment in discount_segments:
            if abs(segment["unit_price"]) < _DISCOUNT_ROW_EPSILON:
                continue
            charges.append({
                "kind": "long_stay_discount",
                "description": "Long Stay Discount",
                "qty": float(segment["nights"]),
                "amount": round(segment["unit_price"], 2),
                "vat_rate": float(segment["vat"]),
                "detail": discount_detail_by_year.get(segment["start"].year),
            })
    else:
        notes.append("No long-stay discount applied (Price Manager tiers/rules did not beat the 7-night rate).")

    # 3. City tax / municipality cost.
    extra_services = _get_extra_services(pricing_data, checkin_year_key, property_name)
    if quotation_flag == SSI_QUOTATION_FLAG:
        city_tax_description = "Municipality Cost (registration)"
        city_tax_rate = extra_services.get("municipality_cost", 0.0)
    else:
        city_tax_description = f"Citytax for {total_guests} person(s)"
        city_tax_rate = extra_services.get("city_tax", 0.0)

    if city_tax_rate > 0:
        charges.append({
            "kind": "city_tax",
            "description": city_tax_description,
            "qty": float(nights * total_guests),
            "amount": round(city_tax_rate, 2),
            "vat_rate": 0.0,
            "detail": None,
        })
    else:
        notes.append(f"{city_tax_description} skipped ({property_name}'s rate is €0).")

    # 4. Extra person charge.
    extra_person_cost = checkin_room_config.get("extra_person_cost", 0.0)
    if total_guests > 1 and extra_person_cost > 0:
        extra_persons = total_guests - 1
        charges.append({
            "kind": "extra_person",
            "description": f"Extra charge for {extra_persons} person(s)",
            "qty": float(nights * extra_persons),
            "amount": round(extra_person_cost, 2),
            "vat_rate": checkin_vat,
            "detail": None,
        })
    elif total_guests > 1:
        notes.append(f"Extra person charge skipped (no extra-person rate configured for {room_name}).")

    # 5. End cleaning.
    charges.append({
        "kind": "end_cleaning",
        "description": "End cleaning",
        "qty": 1.0,
        "amount": round(checkin_room_config.get("end_cleaning", 0.0), 2),
        "vat_rate": checkin_vat,
        "detail": None,
    })

    # 6. Administration costs, based on the running total of everything above.
    running_total = round(sum(c["qty"] * c["amount"] for c in charges), 2)
    city_tax_line_total = round(sum(c["qty"] * c["amount"] for c in charges if c["kind"] == "city_tax"), 2)
    admin_result = admin_costs_service.calculate_admin_costs(
        property_name=property_name,
        total_charges=running_total,
        deposit_amount=0.0,
        city_tax_amount=city_tax_line_total,
    )
    charges.append({
        "kind": "admin_costs",
        "description": "Administration costs",
        "qty": 1.0,
        "amount": admin_result["admin_cost"],
        "vat_rate": checkin_vat,
        "detail": admin_result["description"],
    })

    return {
        "nights": nights,
        "total_guests": total_guests,
        "charges": charges,
        "notes": notes,
    }
