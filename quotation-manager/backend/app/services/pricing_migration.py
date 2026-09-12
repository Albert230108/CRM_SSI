"""One-off (idempotent) conversion of the old calendar-year pricing config to the new
date-range shape (see pricing_config). Each year Y becomes a Y-01-01..Y-12-31 range carrying
that year's tiers. Runs automatically on load so a deployed config volume on the old shape is
migrated in place; a no-op once the config is already in the new shape."""

from __future__ import annotations

from typing import Any


def is_old_shape(data: dict) -> bool:
    """Old shape keys the top level by calendar year (e.g. "2025", "2026")."""
    return any(str(k).isdigit() for k in data)


def normalize_pricing_config(data: dict) -> dict:
    """Return the config in the new per-property / per-room / date-range shape. Idempotent: a
    config already in the new shape is returned unchanged."""
    if not is_old_shape(data):
        return data

    years = sorted((k for k in data if str(k).isdigit()), key=int)
    out: dict[str, Any] = {}
    for year in years:  # ascending, so later years overwrite per-property extra_services / room scalars
        for property_name, property_data in data[year].items():
            prop = out.setdefault(property_name, {"extra_services": {}, "rooms": {}})
            prop["extra_services"] = dict(property_data.get("extra_services", {}))
            for room_name, room_data in property_data.items():
                if room_name == "extra_services":
                    continue
                room = prop["rooms"].setdefault(room_name, {"price_ranges": []})
                room["end_cleaning"] = room_data.get("end_cleaning", 0.0)
                room["extra_person_cost"] = room_data.get("extra_person_cost", 0.0)
                room["price_ranges"].append({
                    "start": f"{year}-01-01",
                    "end": f"{year}-12-31",
                    "price_tiers": dict(room_data.get("price_tiers", {})),
                })
    return out
