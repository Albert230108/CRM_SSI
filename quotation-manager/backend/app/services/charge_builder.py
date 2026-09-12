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

Every internal price lookup and calculation above runs on the VAT-EXCLUSIVE
config values (Settings/base_prices/NewCombinedPrices/admin_costs stay
ex-VAT). Only the final charge amounts handed back to the quotation form are
grossed up per-row (see app.services.vat) to match Beds24's VAT-inclusive
invoice-item amounts - that's the one place the incl.-VAT figures the tenant
actually sees come from.
"""

from datetime import date, timedelta
from typing import Any, Optional

from app.services import admin_costs as admin_costs_service
from app.services import pricing_config
from app.services import vat
from app.services.vat import VAT_2026_START, vat_rate_for_date  # re-exported for existing callers

SSI_QUOTATION_FLAG = "(SSI)"


class ChargeBuilderError(Exception):
    """Raised when a booking can't be priced (bad dates, unknown property/room)."""


def build_standard_charges(
    property_name: str,
    room_name: str,
    checkin_date: date,
    checkout_date: date,
    adults: int = 1,
    children: int = 0,
    quotation_flag: Optional[str] = None,
    pricing_data: Optional[dict] = None,
) -> dict[str, Any]:
    if checkout_date <= checkin_date:
        raise ChargeBuilderError("check_out must be after check_in")

    if pricing_data is None:
        pricing_data = pricing_config.load_pricing_data()

    nights = (checkout_date - checkin_date).days
    total_guests = adults + children
    checkin_vat = vat_rate_for_date(checkin_date)

    # Fail fast on an unknown property/room rather than silently emitting zeros.
    try:
        checkin_room_config = pricing_config.get_room(pricing_data, property_name, room_name)
        segments = pricing_config.accommodation_segments(checkin_room_config, checkin_date, checkout_date, nights)
    except pricing_config.PricingConfigError as exc:
        raise ChargeBuilderError(str(exc)) from exc

    charges: list[dict[str, Any]] = []
    notes: list[str] = []

    # 1. Accommodation, split at the union of the room's date-range boundaries and the 2026-01-01
    # VAT boundary, each segment priced from its own range's tier (selected by total stay length).
    multi_segment = len(segments) > 1
    for segment in segments:
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

    # 2. City tax / municipality cost. Resolved from the check-in date's range (property default
    # unless that range overrides it).
    extra_services = pricing_config.resolve_extra_services(pricing_data, property_name, room_name, checkin_date)
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

    # Everything above priced off the ex-VAT config values (Settings stays
    # ex-VAT). Gross up each row now, once, so what lands on the quotation form
    # matches Beds24's VAT-inclusive invoice-item amounts - e.g. a 58.68 net
    # 7-night tier at 21% becomes the 71.00 that live bookings actually hold.
    for charge in charges:
        net = charge["amount"]
        charge["amount_excl_vat"] = net
        charge["amount"] = vat.gross_amount(net, charge["vat_rate"])

    return {
        "nights": nights,
        "total_guests": total_guests,
        "charges": charges,
        "notes": notes,
    }
