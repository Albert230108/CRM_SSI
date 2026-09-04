"""Admin-only proxy for a whatsapp-service instance's recent journal output.

Added while diagnosing the 2026-09-04 LOGOUT/crash loop: operators needed the service logs from the
admin panel rather than over SSH.
"""

import pytest

from app.services.whatsapp_client import WhatsAppBridgeError


class _FakeLogs:
    """Stands in for fetch_whatsapp_logs, recording how the endpoint called it."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def __call__(self, external_account_id, lines=200):
        self.calls.append({"external_account_id": external_account_id, "lines": lines})
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.fixture
def patch_logs(monkeypatch):
    def _patch(fake):
        monkeypatch.setattr("app.api.whatsapp_thread_links.fetch_whatsapp_logs", fake)
        return fake

    return _patch


# Journal output carries chat ids and phone numbers, a wider exposure than the connection status
# every authenticated user can already read - so this endpoint must be admin-only.
def test_non_admin_cannot_read_service_logs(non_admin_client, patch_logs):
    fake = patch_logs(_FakeLogs(payload={"available": True, "lines": ["secret"], "unit": "u"}))

    response = non_admin_client.get("/api/whatsapp/accounts/ssi-crm-whatsapp/logs")

    assert response.status_code == 403
    assert fake.calls == [], "the bridge must not be called for an unauthorized request"


def test_admin_reads_service_logs(client, patch_logs):
    patch_logs(
        _FakeLogs(
            payload={
                "available": True,
                "unit": "crm-whatsapp-2.service",
                "lines": [
                    "2026-09-04T12:16:03+02:00 ssi-server node[1]: WhatsApp client disconnected: LOGOUT",
                    "2026-09-04T12:16:03+02:00 ssi-server node[1]: Ignored transient WhatsApp page-navigation race",
                ],
                "message": None,
            }
        )
    )

    response = client.get("/api/whatsapp/accounts/ssi-crm-whatsapp/logs")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["unit"] == "crm-whatsapp-2.service"
    assert body["external_account_id"] == "ssi-crm-whatsapp"
    assert len(body["lines"]) == 2
    assert "LOGOUT" in body["lines"][0]


def test_line_count_is_clamped(client, patch_logs):
    fake = patch_logs(_FakeLogs(payload={"available": True, "unit": "u", "lines": []}))

    client.get("/api/whatsapp/accounts/ssi-crm-whatsapp/logs?lines=99999")
    client.get("/api/whatsapp/accounts/ssi-crm-whatsapp/logs?lines=0")

    assert fake.calls[0]["lines"] == 1000
    assert fake.calls[1]["lines"] == 1


# A service that is running but not under systemd is not an error; the panel should say why the box
# is empty rather than render nothing.
def test_unavailable_journal_is_reported_not_raised(client, patch_logs):
    patch_logs(
        _FakeLogs(
            payload={
                "available": False,
                "unit": None,
                "lines": [],
                "message": "Could not determine the systemd unit for this service.",
            }
        )
    )

    response = client.get("/api/whatsapp/accounts/edi-crm-whatsapp/logs")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["lines"] == []
    assert "systemd unit" in body["message"]


def test_unreachable_bridge_surfaces_its_status_code(client, patch_logs):
    patch_logs(_FakeLogs(error=WhatsAppBridgeError(503, "WhatsApp bridge is unavailable")))

    response = client.get("/api/whatsapp/accounts/edi-crm-whatsapp/logs")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]
