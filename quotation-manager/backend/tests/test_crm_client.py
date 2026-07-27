import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app.services import crm_client


def test_get_tenant_context_forwards_token_and_returns_json(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth_header"] = request.headers.get("authorization")
        return httpx.Response(200, json={"tenant_id": 1, "booking_id": "B-1"})

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            return handler(httpx.Request("GET", url, headers=headers))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(crm_client.get_tenant_context(1, "my-token"))

    assert result == {"tenant_id": 1, "booking_id": "B-1"}
    assert captured["auth_header"] == "Bearer my-token"
    assert captured["url"].endswith("/api/quotation/tenant-context/1")


def test_get_beds24_booking_raises_http_exception_on_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Booking not found")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            return handler(httpx.Request("GET", url, headers=headers))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(crm_client.get_beds24_booking("99999", "my-token"))

    assert exc_info.value.status_code == 404


def test_send_invoice_items_posts_json_body(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"status": "ok"})

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return handler(httpx.Request("POST", url, headers=headers))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        crm_client.send_invoice_items_to_beds24("12345", "my-token", {"invoice_items": []})
    )

    assert result == {"status": "ok"}
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/quotation/beds24-booking/12345/invoice-items")
    assert captured["json"] == {"invoice_items": []}
