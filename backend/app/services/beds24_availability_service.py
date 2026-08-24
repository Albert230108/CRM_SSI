"""Parses the raw Beds24 room/studio availability payload into a compact, human-readable
summary text and caches it in a single row (Beds24AvailabilitySummary), refreshed on a
background poll rather than fetched live per draft/brain update - see main.py's scheduler loop.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.beds24_availability_summary import Beds24AvailabilitySummary
from app.services import beds24_client

logger = logging.getLogger(__name__)

# Module-level guard against overlapping refreshes: if a slow Beds24 pagination run overruns the
# scheduler's refresh interval, the next tick must skip rather than start a concurrent fetch that
# could write the single cache row out of order with the run already in flight.
_is_running = False


def _format_date(value: date) -> str:
    return value.strftime("%b %-d")


def _collapse_ranges(day_status: list[tuple[date, bool]]) -> list[tuple[date, date, bool]]:
    ranges: list[tuple[date, date, bool]] = []
    for day, available in sorted(day_status):
        if ranges and ranges[-1][2] == available and (day - ranges[-1][1]).days == 1:
            ranges[-1] = (ranges[-1][0], day, available)
        else:
            ranges.append((day, day, available))
    return ranges


def _format_range(start: date, end: date, available: bool) -> str:
    label = "free" if available else "booked"
    if start == end:
        return f"{label} {_format_date(start)}"
    # Same-month ranges drop the repeated month name on the end date (e.g. "Aug 25-27"); a
    # range crossing months spells both out (e.g. "Aug 25-Sep 5").
    end_label = str(end.day) if start.month == end.month and start.year == end.year else _format_date(end)
    return f"{label} {_format_date(start)}–{end_label}"


def parse_availability_summary(raw_rooms: list[dict[str, Any]]) -> str:
    """Collapses each room's per-date booleans into free/booked date ranges, e.g.
    "Studio 1: booked Aug 25-28, free Aug 29-Sep 5" - never the raw per-date JSON.
    """
    if not raw_rooms:
        return "No availability data on file."

    lines: list[str] = []
    for room in raw_rooms:
        name = str(room.get("name") or f"Room {room.get('roomId', '?')}").strip()
        availability = room.get("availability") or {}
        if not isinstance(availability, dict):
            continue
        day_status: list[tuple[date, bool]] = []
        for date_str, is_available in availability.items():
            try:
                day = date.fromisoformat(str(date_str))
            except ValueError:
                continue
            day_status.append((day, bool(is_available)))
        if not day_status:
            continue
        ranges = _collapse_ranges(day_status)
        range_text = ", ".join(_format_range(start, end, available) for start, end, available in ranges)
        lines.append(f"{name}: {range_text}")

    return "\n".join(lines) if lines else "No availability data on file."


async def refresh_availability_summary(db: Session) -> None:
    global _is_running
    if _is_running:
        logger.info("Beds24 availability refresh already running, skipping this tick")
        return
    _is_running = True
    try:
        raw_rooms = await beds24_client.get_room_availability()
        summary_text = parse_availability_summary(raw_rooms)
        row = db.query(Beds24AvailabilitySummary).first()
        if row is None:
            db.add(Beds24AvailabilitySummary(summary_text=summary_text))
        else:
            row.summary_text = summary_text
            row.refreshed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        _is_running = False


def get_cached_summary(db: Session) -> str:
    row = db.query(Beds24AvailabilitySummary).first()
    return row.summary_text if row is not None else "Availability has not been fetched yet."
