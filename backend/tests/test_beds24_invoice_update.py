import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app.services import beds24_service


@pytest.fixture(autouse=True)
def fake_auth_headers(monkeypatch):
    async def fake_headers():
        return {"accept": "application/json", "token": "fake-token", "Content-Type": "application/json"}

    monkeypatch.setattr(beds24_service, "_auth_headers", fake_headers)


_RealAsyncClient = httpx.AsyncClient


def _client_factory(handler):
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        headers = kwargs.pop("headers", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), headers=headers)

    return factory


def test_update_booking_invoice_items_sends_delete_then_update(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"success": True}])

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    asyncio.run(
        beds24_service.update_booking_invoice_items(
            booking_id="12345",
            original_invoice_item_ids=["item-1", "item-2"],
            final_invoice_items=[{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vatRate": 9}],
        )
    )

    assert len(calls) == 2
    assert b"item-1" in calls[0].content and b"item-2" in calls[0].content
    assert b"Rent" in calls[1].content


def test_update_booking_invoice_items_skips_delete_step_when_no_original_ids(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"success": True}])

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    asyncio.run(
        beds24_service.update_booking_invoice_items(
            booking_id="12345",
            original_invoice_item_ids=[],
            final_invoice_items=[{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vatRate": 9}],
        )
    )

    assert len(calls) == 1


def test_update_booking_invoice_items_raises_on_beds24_rejection(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"success": False, "error": "invalid"}])

    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            beds24_service.update_booking_invoice_items(
                booking_id="12345",
                original_invoice_item_ids=[],
                final_invoice_items=[{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vatRate": 9}],
            )
        )
    assert exc_info.value.status_code == 502
