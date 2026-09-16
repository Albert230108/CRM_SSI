import asyncio
import json

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


def _handler_factory(live_item_ids):
    """Build a MockTransport handler that answers the leading GET (booking with its
    current invoice items) and the subsequent delete/update POSTs, recording POSTs."""
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            invoice_items = [{"id": item_id} for item_id in live_item_ids]
            return httpx.Response(200, json={"data": [{"id": "12345", "invoiceItems": invoice_items}]})
        posts.append(request)
        return httpx.Response(200, json=[{"success": True}])

    return handler, posts


def test_update_booking_invoice_items_sends_delete_then_update(monkeypatch):
    handler, posts = _handler_factory(live_item_ids=["item-1", "item-2"])
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    asyncio.run(
        beds24_service.update_booking_invoice_items(
            booking_id="12345",
            original_invoice_item_ids=["item-1", "item-2"],
            final_invoice_items=[{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vatRate": 9}],
        )
    )

    assert len(posts) == 2
    assert b"item-1" in posts[0].content and b"item-2" in posts[0].content
    assert b"Rent" in posts[1].content


def test_update_booking_invoice_items_deletes_live_ids_not_stale_client_ids(monkeypatch):
    """Regression: a second send from a still-open editor supplies stale client ids
    (the items Beds24 already deleted on the first send). The delete step must target
    the booking's *live* invoice items, not the stale ids, otherwise Beds24 rejects
    the update with 'invalid id'."""
    handler, posts = _handler_factory(live_item_ids=["171421226", "171421227"])
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    asyncio.run(
        beds24_service.update_booking_invoice_items(
            booking_id="12345",
            original_invoice_item_ids=["stale-1", "stale-2"],
            final_invoice_items=[{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vatRate": 9}],
        )
    )

    assert len(posts) == 2
    delete_body = posts[0].content
    assert b"171421226" in delete_body and b"171421227" in delete_body
    assert b"stale-1" not in delete_body and b"stale-2" not in delete_body


def test_update_booking_invoice_items_skips_delete_when_booking_has_no_live_items(monkeypatch):
    """Second-send idempotency: when Beds24 already holds the new set (the live
    booking has no items to delete, e.g. a resend after items were cleared), only the
    recreate POST is issued and no delete_invoice_items call happens."""
    handler, posts = _handler_factory(live_item_ids=[])
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    asyncio.run(
        beds24_service.update_booking_invoice_items(
            booking_id="12345",
            original_invoice_item_ids=["stale-1"],
            final_invoice_items=[{"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "vatRate": 9}],
        )
    )

    assert len(posts) == 1
    assert b"Rent" in posts[0].content


def test_update_booking_invoice_items_raises_on_beds24_rejection(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "12345", "invoiceItems": []}]})
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


def test_update_booking_invoice_items_sends_booking_fields_on_update(monkeypatch):
    """D1: status / subStatus / flagText ride on the same update call as the invoice items, and
    None values are omitted so an invoice-items-only push is unchanged."""
    handler, posts = _handler_factory(live_item_ids=[])
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    asyncio.run(
        beds24_service.update_booking_invoice_items(
            booking_id="12345",
            original_invoice_item_ids=[],
            final_invoice_items=[{"type": "charge", "description": "Rent", "qty": 1, "amount": 10.0, "vatRate": 9}],
            booking_fields={"status": "confirmed", "subStatus": "keys collected", "flagText": None},
        )
    )

    assert len(posts) == 1
    body = posts[0].content
    assert b"confirmed" in body and b"keys collected" in body
    # None-valued fields are dropped, not sent as null.
    assert b"flagText" not in body


def test_update_booking_invoice_items_sends_empty_flag_text_to_clear_flag(monkeypatch):
    """An emptied Flag in the quotation editor arrives as flagText "" and must reach Beds24 (only
    None is dropped), otherwise the booking's existing flag could never be cleared."""
    handler, posts = _handler_factory(live_item_ids=[])
    monkeypatch.setattr(httpx, "AsyncClient", _client_factory(handler))

    asyncio.run(
        beds24_service.update_booking_invoice_items(
            booking_id="12345",
            original_invoice_item_ids=[],
            final_invoice_items=[{"type": "charge", "description": "Rent", "qty": 1, "amount": 10.0, "vatRate": 9}],
            booking_fields={"status": "inquiry", "subStatus": None, "flagText": ""},
        )
    )

    assert len(posts) == 1
    body = json.loads(posts[0].content)
    payload = body[0] if isinstance(body, list) else body
    assert payload["flagText"] == ""
    assert "subStatus" not in payload
