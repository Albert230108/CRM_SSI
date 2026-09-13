"""
Auto-generates the standard invoice charge-line stack for a booking, ported
from the desktop Quotation Manager's update_predefined_rows
(Python-EmailQuotation-1/src/interface.py). The web port previously had no
equivalent: the editor only loaded whatever invoiceItems already existed on
the Beds24 booking and left a human to build the rest by hand.

Builds, in order:
1. Accommodation - split across the 2026-01-01 VAT boundary (9% before, 21%
   from 2026) and the room's date-range boundaries, priced at each range's
   shortest-stay ("7-night") rack rate. A stay longer than 183 nights that
   does NOT cross the VAT boundary is charged at 0% VAT (desktop rule).
2. Long Stay Discount - a negative row, per accommodation segment, bringing
   the rack rate down to the tier selected by the total stay length.
3. City tax, or "Municipality Cost (registration)" when the quotation flag
   normalizes to "SSI". Emitted even at a €0 rate, split per VAT segment.
4. Extra person charge, when there's more than one guest (emitted even at a
   €0 rate), split per VAT segment so each segment carries its own VAT rate.
5. End cleaning.
6. Administration costs, via the already-ported admin_costs service, based
   on the running VAT-INCLUSIVE total of the rows above.

Every internal price lookup runs on the VAT-EXCLUSIVE config values
(Settings/NewCombinedPrices/admin_costs stay ex-VAT). Each charge row is
grossed up as it is built (see app.services.vat) so what lands on the
quotation form matches Beds24's VAT-inclusive invoice-item amounts. Because
the admin step (6) bases its fee on the running VAT-inclusive total - exactly
as the desktop did - rows must already be grossed by the time it runs, which
is why the gross-up happens inline rather than once at the end.
"""

from datetime import date, timedelta
from typing import Any, Optional

from app.services import admin_costs as admin_costs_service
from app.services import pricing_config
from app.services import vat
from app.services.vat import VAT_2026_START, vat_rate_for_date  # re-exported for existing callers

# Nights above this threshold price accommodation at 0% VAT when the stay does not cross the
# 2026-01-01 VAT boundary (the desktop's LONG_STAY_DEPOSIT_NIGHT_THRESHOLD / single-period rule).
LONG_STAY_NIGHT_THRESHOLD = 183


class ChargeBuilderError(Exception):
    """Raised when a booking can't be priced (bad dates, unknown property/room)."""


def _normalize_flag(quotation_flag: Optional[str]) -> str:
    """Desktop flag normalization: strip parentheses/whitespace and upper-case, so "(SSI)",
    "SSI" and " (ssi) " all resolve to "SSI"."""
    return (quotation_flag or "").replace("(", "").replace(")", "").strip().upper()


def _vat_segments(checkin_date: date, checkout_date: date) -> list[dict[str, Any]]:
    """Split [checkin, checkout) at the 2026-01-01 VAT boundary only (one segment normally, two
    when the stay crosses it). Used for the city-tax and extra-person rows, which the desktop
    emitted one-per-VAT-segment on a spanning stay."""
    if checkin_date < VAT_2026_START < checkout_date:
        points = [checkin_date, VAT_2026_START, checkout_date]
    else:
        points = [checkin_date, checkout_date]
    segments: list[dict[str, Any]] = []
    for seg_start, seg_end in zip(points, points[1:]):
        segments.append({
            "start": seg_start,
            "end": seg_end,
            "nights": (seg_end - seg_start).days,
            "vat": vat_rate_for_date(seg_start),
        })
    return segments


def _append(charges: list[dict[str, Any]], kind: str, description: str, qty: float,
            net_amount: float, vat_rate: float, detail: Optional[str] = None) -> None:
    """Append a charge row, grossing the ex-VAT `net_amount` up to the VAT-inclusive amount the
    form/Beds24 holds and keeping the ex-VAT value alongside for reference.

    The gross-up uses the FULL-PRECISION net and rounds exactly once (matching the desktop's
    `round((actual-base)*(1+vat/100), 2)`). Pre-rounding the net to 2 dp first would double-round
    and land a cent off on some values - e.g. a -8.26446 @21% per-night discount would show -9.99
    instead of -10.00."""
    charges.append({
        "kind": kind,
        "description": description,
        "qty": float(qty),
        "amount": vat.gross_amount(net_amount, vat_rate),
        "amount_excl_vat": round(net_amount, 2),
        "vat_rate": float(vat_rate),
        "detail": detail,
    })


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
    vat_spans = checkin_date < VAT_2026_START < checkout_date
    # Desktop applies the 0% long-stay VAT only in its single-VAT-period branch: a >183-night stay
    # that crosses 2026-01-01 still bills per-segment 9%/21%.
    long_stay_zero_vat = (not vat_spans) and nights > LONG_STAY_NIGHT_THRESHOLD

    # Fail fast on an unknown property/room rather than silently emitting zeros.
    try:
        checkin_room_config = pricing_config.get_room(pricing_data, property_name, room_name)
        segments = pricing_config.accommodation_segments(checkin_room_config, checkin_date, checkout_date, nights)
    except pricing_config.PricingConfigError as exc:
        raise ChargeBuilderError(str(exc)) from exc

    charges: list[dict[str, Any]] = []
    notes: list[str] = []

    def _acc_vat(segment: dict[str, Any]) -> float:
        return 0.0 if long_stay_zero_vat else float(segment["vat"])

    # 1. Accommodation at each segment's shortest-stay (rack) rate. Split at the union of the
    # room's date-range boundaries and the 2026-01-01 VAT boundary.
    multi_segment = len(segments) > 1
    for segment in segments:
        start_display = segment["start"].strftime("%d-%b-%Y")
        if multi_segment:
            end_display = (segment["end"] - timedelta(days=1)).strftime("%d-%b-%Y")
            description = f"{room_name} - {start_display} to {end_display}"
        else:
            end_display = checkout_date.strftime("%d-%b-%Y")
            description = f"{room_name} - {start_display} - {end_display}"
        if long_stay_zero_vat:
            description += " (excl. VAT)"
        _append(charges, "accommodation", description, segment["nights"],
                segment["base_unit"], _acc_vat(segment))

    # 2. Long Stay Discount - per segment, the rack rate minus the tier selected by total nights.
    for segment in segments:
        base_unit = segment["base_unit"]
        actual_unit = segment["unit_price"]
        if actual_unit < base_unit:
            seg_vat = _acc_vat(segment)
            description = f"Long Stay Discount ({segment['nights']} nights)"
            _append(charges, "long_stay_discount", description, segment["nights"],
                    actual_unit - base_unit, seg_vat)

    # 3. City tax / municipality cost (VAT 0), emitted even at €0, split per VAT segment.
    extra_services = pricing_config.resolve_extra_services(pricing_data, property_name, room_name, checkin_date)
    if _normalize_flag(quotation_flag) == "SSI":
        city_tax_label = "Municipality Cost (registration)"
        city_tax_rate = extra_services.get("municipality_cost", 0.0)
        label_gets_dates = False
    else:
        city_tax_label = f"Citytax for {total_guests} person(s)"
        city_tax_rate = extra_services.get("city_tax", 0.0)
        label_gets_dates = True

    anc_segments = _vat_segments(checkin_date, checkout_date)
    anc_multi = len(anc_segments) > 1
    for segment in anc_segments:
        description = city_tax_label
        if anc_multi and label_gets_dates:
            start_display = segment["start"].strftime("%d-%b-%Y")
            end_display = (segment["end"] - timedelta(days=1)).strftime("%d-%b-%Y")
            description = f"{city_tax_label} - {start_display} to {end_display}"
        _append(charges, "city_tax", description, segment["nights"] * total_guests,
                city_tax_rate, 0.0)

    # 4. Extra person charge - emitted even at €0, split per VAT segment (each carries its own rate).
    extra_person_cost = checkin_room_config.get("extra_person_cost", 0.0)
    if total_guests > 1:
        extra_persons = total_guests - 1
        for segment in anc_segments:
            _append(charges, "extra_person", f"Extra charge for {extra_persons} person(s)",
                    segment["nights"] * extra_persons, extra_person_cost, float(segment["vat"]))

    # 5. End cleaning (check-in VAT rate; no long-stay 0% here, matching the desktop).
    _append(charges, "end_cleaning", "End cleaning", 1,
            checkin_room_config.get("end_cleaning", 0.0), checkin_vat)

    # 6. Administration costs. Desktop-exact: the base is the running VAT-INCLUSIVE total of the
    # rows above minus the Citytax line (Municipality Cost is intentionally NOT subtracted); the
    # percentage is applied and clamped against the ex-VAT min/max, then grossed up AGAIN by the
    # check-in VAT rate. That deliberate double-VAT step is part of the desktop behavior.
    running_gross = round(sum(c["qty"] * c["amount"] for c in charges), 2)
    citytax_gross = round(
        sum(c["qty"] * c["amount"] for c in charges
            if "city" in c["description"].lower() and "tax" in c["description"].lower()),
        2,
    )
    admin_result = admin_costs_service.calculate_admin_costs(
        property_name=property_name,
        total_charges=running_gross,
        deposit_amount=0.0,
        city_tax_amount=citytax_gross,
    )
    admin_incl = round(admin_result["admin_cost"] * (1 + checkin_vat / 100.0), 2)
    charges.append({
        "kind": "admin_costs",
        "description": "Administration costs",
        "qty": 1.0,
        "amount": admin_incl,
        "amount_excl_vat": admin_result["admin_cost"],
        "vat_rate": float(checkin_vat),
        "detail": admin_result["description"],
    })

    return {
        "nights": nights,
        "total_guests": total_guests,
        "charges": charges,
        "notes": notes,
    }
