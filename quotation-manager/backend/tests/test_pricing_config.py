from datetime import date

import pytest

from app.services import pricing_config
from app.services.pricing_migration import normalize_pricing_config


ROOM = {
    "end_cleaning": 50.0,
    "extra_person_cost": 5.0,
    "price_ranges": [
        {"start": "2026-01-01", "end": "2026-05-31", "price_tiers": {"7": 100.0, "30": 80.0}},
        {"start": "2026-06-01", "end": "2026-08-31", "price_tiers": {"7": 150.0, "30": 120.0},
         "extra_services": {"deposit": 999.0}},
    ],
}
DATA = {"P": {"extra_services": {"deposit": 400.0, "city_tax": 3.0}, "rooms": {"R": ROOM}}}


def test_select_tier_picks_highest_breakpoint_at_or_below_nights():
    assert pricing_config.select_tier_price({"7": 100.0, "14": 90.0, "30": 80.0}, 7) == 100.0
    assert pricing_config.select_tier_price({"7": 100.0, "14": 90.0, "30": 80.0}, 20) == 90.0
    assert pricing_config.select_tier_price({"7": 100.0, "14": 90.0, "30": 80.0}, 45) == 80.0
    # Shorter than the smallest breakpoint -> use the smallest.
    assert pricing_config.select_tier_price({"7": 100.0, "30": 80.0}, 3) == 100.0


def test_select_tier_supports_arbitrary_flexible_breakpoints():
    assert pricing_config.select_tier_price({"3": 200.0, "21": 150.0}, 10) == 200.0
    assert pricing_config.select_tier_price({"3": 200.0, "21": 150.0}, 25) == 150.0


def test_resolve_range_falls_back_to_latest_past_range():
    # A 2027 date isn't in any range -> use the latest range that starts on/before it.
    rng = pricing_config.resolve_range(ROOM, date(2027, 2, 1))
    assert rng["start"] == "2026-06-01"


def test_resolve_extra_services_overlays_range_over_property_default():
    # Summer range overrides the deposit; city_tax falls back to the property default.
    summer = pricing_config.resolve_extra_services(DATA, "P", "R", date(2026, 7, 1))
    assert summer["deposit"] == 999.0 and summer["city_tax"] == 3.0
    # Spring range has no override -> property default deposit.
    spring = pricing_config.resolve_extra_services(DATA, "P", "R", date(2026, 3, 1))
    assert spring["deposit"] == 400.0


def test_accommodation_segments_splits_at_range_boundary():
    # A stay crossing the spring/summer boundary splits into two segments priced from each range.
    segments = pricing_config.accommodation_segments(ROOM, date(2026, 5, 30), date(2026, 6, 3), nights=4)
    assert [s["nights"] for s in segments] == [2, 2]
    assert segments[0]["unit_price"] == 100.0  # spring 7-tier (4 nights)
    assert segments[1]["unit_price"] == 150.0  # summer 7-tier


def test_migration_is_idempotent():
    old = {"2026": {"P": {"extra_services": {"deposit": 400.0}, "R": {"price_tiers": {"7": 100.0}, "end_cleaning": 50.0, "extra_person_cost": 5.0}}}}
    once = normalize_pricing_config(old)
    assert once == normalize_pricing_config(once)
    assert once["P"]["rooms"]["R"]["price_ranges"][0]["start"] == "2026-01-01"
