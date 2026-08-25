from app.models.beds24_availability_summary import Beds24AvailabilitySummary


def test_get_availability_defaults_when_never_refreshed(non_admin_client):
    response = non_admin_client.get("/api/beds24-availability")
    assert response.status_code == 200
    assert response.json()["summary_text"] == "Availability has not been fetched yet."
    assert response.json()["refreshed_at"] is None
    assert response.json()["rooms"] == []


def test_get_availability_returns_cached_summary(non_admin_client, db_session):
    db_session.add(Beds24AvailabilitySummary(summary_text="Studio 1: free Aug 25-27"))
    db_session.commit()

    response = non_admin_client.get("/api/beds24-availability")

    assert response.status_code == 200
    assert response.json()["summary_text"] == "Studio 1: free Aug 25-27"


def test_get_availability_returns_structured_rooms(non_admin_client, db_session):
    db_session.add(
        Beds24AvailabilitySummary(
            summary_text="Studio 1: free Aug 25-26",
            rooms_json=[{"room_name": "Studio 1", "free_ranges": [{"check_in": "2026-08-25", "check_out": "2026-08-27"}]}],
        )
    )
    db_session.commit()

    response = non_admin_client.get("/api/beds24-availability")

    assert response.status_code == 200
    assert response.json()["rooms"] == [
        {"room_name": "Studio 1", "free_ranges": [{"check_in": "2026-08-25", "check_out": "2026-08-27"}]}
    ]
