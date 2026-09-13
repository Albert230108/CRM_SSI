"""Date-range price tiers - the single pricing source for the Quotation Manager.

Replaces the previous calendar-year keying (and the separate base_prices / discount systems).
`NewCombinedPrices.json` is now shaped per property -> rooms -> date ranges, each range carrying
its own night-count tiers and optional extra-services overrides:

    {
      "<property>": {
        "extra_services": {"deposit": .., "city_tax": .., "municipality_cost": ..},  # defaults
        "rooms": {
          "<room>": {
            "end_cleaning": .., "extra_person_cost": ..,
            "price_ranges": [
              {"start": "2026-01-01", "end": "2026-12-31",
               "price_tiers": {"7": .., "14": .., "30": ..},        # any night-count breakpoints
               "extra_services": {"deposit": ..}}                   # optional per-range overrides
            ]
          }
        }
      }
    }

Tiers are flexible: a range may define any set of night-count breakpoints; the applicable rate is
the highest breakpoint <= the total stay length. A stay spanning range/VAT boundaries is split and
each segment priced from its own range (see accommodation_segments)."""

from __future__ import annotations

import json
import pathlib
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.services.vat import VAT_2026_START, vat_rate_for_date

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
PRICING_FILE = DATA_DIR / "NewCombinedPrices.json"

_pricing_cache: Optional[dict] = None


class PricingConfigError(Exception):
    """Raised when pricing data is missing or a property/room can't be resolved."""


def bust_cache() -> None:
    global _pricing_cache
    _pricing_cache = None


def load_pricing_data(force_reload: bool = False) -> dict:
    global _pricing_cache
    if _pricing_cache is not None and not force_reload:
        return _pricing_cache
    if not PRICING_FILE.exists():
        raise PricingConfigError("NewCombinedPrices.json not found")
    with open(PRICING_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Migrate an old calendar-year config (e.g. a pre-existing deployed volume) to the new
    # date-range shape in place, so the rest of the code only ever sees the new structure.
    from app.services import pricing_migration

    if pricing_migration.is_old_shape(data):
        data = pricing_migration.normalize_pricing_config(data)
        try:
            with open(PRICING_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass  # read-only config dir is fine; we still use the normalized data in memory
    _pricing_cache = data
    return _pricing_cache


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def get_property(pricing_data: dict, property_name: str) -> dict:
    try:
        return pricing_data[property_name]
    except KeyError:
        raise PricingConfigError(f"Unknown property: {property_name}") from None


def get_room(pricing_data: dict, property_name: str, room_name: str) -> dict:
    rooms = get_property(pricing_data, property_name).get("rooms", {})
    try:
        return rooms[room_name]
    except KeyError:
        raise PricingConfigError(f"Unknown room '{room_name}' for property '{property_name}'") from None


def resolve_range(room: dict, d: date) -> dict:
    """The price range covering date `d`. If none contains it, fall back to the latest range that
    starts on/before `d` (so a stay past the last defined range keeps working), else the earliest."""
    ranges = room.get("price_ranges", [])
    if not ranges:
        raise PricingConfigError("Room has no price ranges defined")
    containing = [r for r in ranges if _parse(r["start"]) <= d <= _parse(r["end"])]
    if containing:
        return containing[0]
    earlier = sorted((r for r in ranges if _parse(r["start"]) <= d), key=lambda r: r["start"])
    if earlier:
        return earlier[-1]
    return sorted(ranges, key=lambda r: r["start"])[0]


def select_tier_price(price_tiers: dict, nights: int) -> float:
    """Highest night-count breakpoint *strictly less than* `nights` (flexible: any breakpoints).
    If the stay is at or below the smallest breakpoint, use the smallest. Raises if there are
    no tiers.

    The strict `<` reproduces the desktop Quotation Manager's tier thresholds, which used strict
    `>` comparisons (nights > 90 -> "90", > 60 -> "60", ... else "7"). So a stay of *exactly* a
    breakpoint length falls to the tier below it: 14 nights -> the "7" rate, 30 -> "14",
    60 -> "30", 90 -> "60". Matching this exactly is required for parity with the desktop app."""
    breakpoints = sorted(int(k) for k in price_tiers)
    if not breakpoints:
        raise PricingConfigError("Price range has no tiers defined")
    applicable = [b for b in breakpoints if b < nights]
    chosen = applicable[-1] if applicable else breakpoints[0]
    return float(price_tiers[str(chosen)])


def shortest_tier_price(price_tiers: dict) -> float:
    """The smallest-breakpoint (shortest-stay) rate - the desktop's "7-night" rack rate, which
    accommodation is priced at before the Long Stay Discount line brings it down to the selected
    tier. Raises if there are no tiers."""
    breakpoints = sorted(int(k) for k in price_tiers)
    if not breakpoints:
        raise PricingConfigError("Price range has no tiers defined")
    return float(price_tiers[str(breakpoints[0])])


def resolve_extra_services(pricing_data: dict, property_name: str, room_name: str, d: date) -> dict:
    """Property-level extra_services defaults, overlaid with the covering range's overrides."""
    merged = dict(get_property(pricing_data, property_name).get("extra_services", {}))
    try:
        rng = resolve_range(get_room(pricing_data, property_name, room_name), d)
    except PricingConfigError:
        return merged
    merged.update({k: v for k, v in (rng.get("extra_services") or {}).items() if v is not None})
    return merged


def accommodation_segments(room: dict, checkin: date, checkout: date, nights: int) -> list[dict[str, Any]]:
    """Split [checkin, checkout) at the union of the room's date-range boundaries and the VAT-2026
    boundary, pricing each segment from its own range's tier (selected by total `nights`)."""
    boundaries = {checkin, checkout}
    if checkin < VAT_2026_START < checkout:
        boundaries.add(VAT_2026_START)
    for r in room.get("price_ranges", []):
        start, end_next = _parse(r["start"]), _parse(r["end"]) + timedelta(days=1)
        if checkin < start < checkout:
            boundaries.add(start)
        if checkin < end_next < checkout:
            boundaries.add(end_next)
    points = sorted(boundaries)

    segments: list[dict[str, Any]] = []
    for seg_start, seg_end in zip(points, points[1:]):
        seg_nights = (seg_end - seg_start).days
        if seg_nights <= 0:
            continue
        rng = resolve_range(room, seg_start)
        price_tiers = rng.get("price_tiers", {})
        segments.append({
            "start": seg_start,
            "end": seg_end,
            "nights": seg_nights,
            # unit_price is the *selected* tier (by total stay length); base_unit is the range's
            # shortest-stay rate. charge_builder prices accommodation at base_unit and emits a
            # negative Long Stay Discount line down to unit_price, matching the desktop.
            "unit_price": select_tier_price(price_tiers, nights),
            "base_unit": shortest_tier_price(price_tiers),
            "vat": vat_rate_for_date(seg_start),
        })
    return segments
