import asyncio

from app.models.beds24_availability_summary import Beds24AvailabilitySummary
from app.services import beds24_availability_service


def test_parse_availability_summary_collapses_consecutive_ranges():
    raw = [
        {
            "roomId": 1,
            "name": "Studio 1",
            "availability": {
                "2026-08-25": False,
                "2026-08-26": False,
                "2026-08-27": False,
                "2026-08-28": True,
                "2026-08-29": True,
            },
        }
    ]

    summary = beds24_availability_service.parse_availability_summary(raw)

    assert summary == "Studio 1: booked Aug 25–27, free Aug 28–29"


def test_parse_availability_summary_spells_out_month_on_cross_month_range():
    raw = [
        {
            "roomId": 1,
            "name": "Studio 1",
            "availability": {"2026-08-29": True, "2026-08-30": True, "2026-08-31": True, "2026-09-01": True},
        }
    ]

    summary = beds24_availability_service.parse_availability_summary(raw)

    assert summary == "Studio 1: free Aug 29–Sep 1"


def test_parse_availability_summary_handles_multiple_rooms():
    raw = [
        {"roomId": 1, "name": "Studio 1", "availability": {"2026-08-25": True}},
        {"roomId": 2, "name": "Studio 2", "availability": {"2026-08-25": False}},
    ]

    summary = beds24_availability_service.parse_availability_summary(raw)

    assert "Studio 1: free Aug 25" in summary
    assert "Studio 2: booked Aug 25" in summary


def test_parse_availability_summary_empty_input():
    assert beds24_availability_service.parse_availability_summary([]) == "No availability data on file."


def test_get_cached_summary_defaults_when_never_refreshed(db_session):
    assert beds24_availability_service.get_cached_summary(db_session) == "Availability has not been fetched yet."


def test_refresh_availability_summary_upserts_single_row(db_session, monkeypatch):
    async def fake_get_room_availability():
        return [{"roomId": 1, "name": "Studio 1", "availability": {"2026-08-25": True}}]

    monkeypatch.setattr(beds24_availability_service.beds24_client, "get_room_availability", fake_get_room_availability)

    asyncio.run(beds24_availability_service.refresh_availability_summary(db_session))
    db_session.commit()

    assert db_session.query(Beds24AvailabilitySummary).count() == 1
    assert beds24_availability_service.get_cached_summary(db_session) == "Studio 1: free Aug 25"

    # A second refresh overwrites the same row rather than adding another.
    async def fake_get_room_availability_updated():
        return [{"roomId": 1, "name": "Studio 1", "availability": {"2026-08-25": False}}]

    monkeypatch.setattr(beds24_availability_service.beds24_client, "get_room_availability", fake_get_room_availability_updated)
    asyncio.run(beds24_availability_service.refresh_availability_summary(db_session))
    db_session.commit()

    assert db_session.query(Beds24AvailabilitySummary).count() == 1
    assert beds24_availability_service.get_cached_summary(db_session) == "Studio 1: booked Aug 25"


def test_refresh_skips_when_already_running(db_session, monkeypatch):
    calls = {"n": 0}

    async def fake_get_room_availability():
        calls["n"] += 1
        return []

    monkeypatch.setattr(beds24_availability_service.beds24_client, "get_room_availability", fake_get_room_availability)
    monkeypatch.setattr(beds24_availability_service, "_is_running", True)

    asyncio.run(beds24_availability_service.refresh_availability_summary(db_session))

    assert calls["n"] == 0
    assert db_session.query(Beds24AvailabilitySummary).count() == 0
