import asyncio
import json

import httpx
import pytest

from app.services import whatsapp_client
from app.services.whatsapp_client import WhatsAppBridgeError


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "", content_type: str = "application/json", json_error: Exception | None = None):
        self.status_code = status_code
        self._payload = payload
        self._text = text
        self._content_type = content_type
        self._json_error = json_error
        self.headers = {"content-type": content_type}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload

    @property
    def text(self) -> str:
        return self._text


class FakeAsyncClient:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        if self.error is not None:
            raise self.error
        return self.response


def run(coro):
    return asyncio.run(coro)


def test_resolve_service_url_prefers_account_map(monkeypatch):
    monkeypatch.setattr(whatsapp_client, "WHATSAPP_SERVICE_URL", "http://host.docker.internal:3001")
    monkeypatch.setattr(
        whatsapp_client,
        "WHATSAPP_SERVICE_URL_MAP",
        json.dumps({
            "client-a": "http://bridge-a.internal:3001",
            "12": "http://bridge-b.internal:3001",
        }),
    )

    assert whatsapp_client._resolve_service_url("client-a", 12) == "http://bridge-a.internal:3001"
    assert whatsapp_client._resolve_service_url("missing", 12) == "http://bridge-b.internal:3001"
    assert whatsapp_client._resolve_service_url("missing", 99) == "http://host.docker.internal:3001"


def test_send_whatsapp_message_translates_timeout_to_503(monkeypatch):
    request = httpx.Request("POST", "http://example.invalid/send")
    fake_client = FakeAsyncClient(error=httpx.ReadTimeout("timed out", request=request))
    monkeypatch.setattr(whatsapp_client.httpx, "AsyncClient", lambda timeout=None: fake_client)

    with pytest.raises(WhatsAppBridgeError) as excinfo:
        run(
            whatsapp_client.send_whatsapp_message(
                {
                    "to": "+31600000000",
                    "message": "Hello",
                    "tenant_id": 1,
                    "external_account_id": "edi-crm-whatsapp",
                    "whatsapp_endpoint_id": 1,
                }
            )
        )

    assert excinfo.value.status_code == 503
    assert str(excinfo.value) == "WhatsApp bridge request timed out"


def test_send_whatsapp_message_translates_connection_error_to_503(monkeypatch):
    request = httpx.Request("POST", "http://example.invalid/send")
    fake_client = FakeAsyncClient(error=httpx.ConnectError("connection failed", request=request))
    monkeypatch.setattr(whatsapp_client.httpx, "AsyncClient", lambda timeout=None: fake_client)

    with pytest.raises(WhatsAppBridgeError) as excinfo:
        run(
            whatsapp_client.send_whatsapp_message(
                {
                    "to": "+31600000000",
                    "message": "Hello",
                    "tenant_id": 1,
                    "external_account_id": "edi-crm-whatsapp",
                    "whatsapp_endpoint_id": 1,
                }
            )
        )

    assert excinfo.value.status_code == 503
    assert str(excinfo.value) == "WhatsApp bridge is unavailable"


def test_send_whatsapp_message_translates_invalid_json_to_502(monkeypatch):
    fake_response = FakeResponse(200, json_error=ValueError("bad json"))
    fake_client = FakeAsyncClient(response=fake_response)
    monkeypatch.setattr(whatsapp_client.httpx, "AsyncClient", lambda timeout=None: fake_client)

    with pytest.raises(WhatsAppBridgeError) as excinfo:
        run(
            whatsapp_client.send_whatsapp_message(
                {
                    "to": "+31600000000",
                    "message": "Hello",
                    "tenant_id": 1,
                    "external_account_id": "edi-crm-whatsapp",
                    "whatsapp_endpoint_id": 1,
                }
            )
        )

    assert excinfo.value.status_code == 502
    assert str(excinfo.value) == "WhatsApp bridge returned invalid JSON"


def test_send_whatsapp_message_maps_upstream_5xx_to_503(monkeypatch):
    fake_response = FakeResponse(500, payload={"error": "bridge exploded"}, text="bridge exploded")
    fake_client = FakeAsyncClient(response=fake_response)
    monkeypatch.setattr(whatsapp_client.httpx, "AsyncClient", lambda timeout=None: fake_client)

    with pytest.raises(WhatsAppBridgeError) as excinfo:
        run(
            whatsapp_client.send_whatsapp_message(
                {
                    "to": "+31600000000",
                    "message": "Hello",
                    "tenant_id": 1,
                    "external_account_id": "edi-crm-whatsapp",
                    "whatsapp_endpoint_id": 1,
                }
            )
        )

    assert excinfo.value.status_code == 503
    assert str(excinfo.value) == "bridge exploded"

