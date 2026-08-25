"""Parses the raw Beds24 room/studio availability payload into a compact, human-readable
summary text and caches it in a single row (Beds24AvailabilitySummary), refreshed on a
background poll rather than fetched live per draft/brain update - see main.py's scheduler loop.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
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


def parse_availability_structured(raw_rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Structured, free-ranges-only counterpart to parse_availability_summary, for the
    Availability tab UI (which formats/labels dates itself rather than consuming prose).

    A free range spans available *nights* [start..end]; check_out is the morning after the
    last available night (end + 1 day), matching how a real booking's check-in/check-out dates
    work - not the last available day itself.
    """
    rooms: list[dict[str, Any]] = []
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
        free_ranges = [
            {"check_in": start.isoformat(), "check_out": (end + timedelta(days=1)).isoformat()}
            for start, end, available in _collapse_ranges(day_status)
            if available
        ]
        if free_ranges:
            rooms.append({"room_name": name, "free_ranges": free_ranges})
    return rooms


async def refresh_availability_summary(db: Session) -> None:
    global _is_running
    if _is_running:
        logger.info("Beds24 availability refresh already running, skipping this tick")
        return
    _is_running = True
    try:
        raw_rooms = await beds24_client.get_room_availability()
        summary_text = parse_availability_summary(raw_rooms)
        rooms_json = parse_availability_structured(raw_rooms)
        row = db.query(Beds24AvailabilitySummary).first()
        if row is None:
            db.add(Beds24AvailabilitySummary(summary_text=summary_text, rooms_json=rooms_json))
        else:
            row.summary_text = summary_text
            row.rooms_json = rooms_json
            row.refreshed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        _is_running = False


def get_cached_summary(db: Session) -> str:
    row = db.query(Beds24AvailabilitySummary).first()
    return row.summary_text if row is not None else "Availability has not been fetched yet."
