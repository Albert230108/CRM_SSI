"""
Regression tests for Beds24's single-booking fetch.

get_booking_detail used to request GET /v2/bookings/{id}. Beds24 v2 has no path-parameter
form for a single booking and answered 500 "Could not process request" for every id -- 100%
of calls failed. In sync-all that was hidden by a bare except/fallback; the booking-preview
endpoint had no fallback and so always returned 502.

The supported shape is the collection endpoint filtered by `id`. Note that Beds24 silently
ignores an unrecognised filter name and answers 200 with the whole unfiltered booking list,
so the returned id is verified rather than trusted.
"""

import httpx
import pytest

from app.services import beds24_client


@pytest.fixture(autouse=True)
def stub_auth(monkeypatch):
    async def fake_headers():
        return {"Authorization": "test-token"}

    monkeypatch.setattr(beds24_client, "_async_headers", fake_headers)


def make_response(payload, url="https://api.beds24.com/v2/bookings"):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_get_booking_detail_queries_collection_endpoint_with_id(monkeypatch):
    captured = {}

    async def fake_get_with_retry(client, url, params):
        captured["url"] = url
        captured["params"] = params
        return make_response({"success": True, "data": [{"id": 90724558, "firstName": "Danielle"}]})

    monkeypatch.setattr(beds24_client, "_get_with_retry", fake_get_with_retry)

    result = await beds24_client.get_booking_detail("90724558")

    # The path-parameter form is what 500s; it must not be used.
    assert captured["url"] == f"{beds24_client.READ_BASE_URL}/bookings"
    assert "/bookings/90724558" not in captured["url"]
    assert captured["params"]["id"] == "90724558"
    assert captured["params"]["includeInfoItems"] == "true"
    assert result["firstName"] == "Danielle"


@pytest.mark.asyncio
async def test_get_booking_detail_unwraps_single_element_list(monkeypatch):
    async def fake_get_with_retry(client, url, params):
        return make_response({"success": True, "count": 1, "data": [{"id": 42, "email": "a@b.c"}]})

    monkeypatch.setattr(beds24_client, "_get_with_retry", fake_get_with_retry)

    result = await beds24_client.get_booking_detail("42")

    assert isinstance(result, dict)
    assert result["id"] == 42


@pytest.mark.asyncio
async def test_get_booking_detail_rejects_a_different_booking(monkeypatch):
    """An ignored filter returns the full list; returning someone else's booking would be worse
    than failing, since the caller writes these fields onto a tenant."""

    async def fake_get_with_retry(client, url, params):
        return make_response({"success": True, "count": 42, "data": [{"id": 111, "email": "wrong@x.y"}]})

    monkeypatch.setattr(beds24_client, "_get_with_retry", fake_get_with_retry)

    with pytest.raises(Exception) as excinfo:
        await beds24_client.get_booking_detail("999")

    assert getattr(excinfo.value, "status_code", None) == 502
