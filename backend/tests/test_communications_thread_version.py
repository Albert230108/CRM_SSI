from datetime import datetime, timedelta, timezone

from app.models.communication import Communication
from app.models.tenant import Tenant


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def add_whatsapp_message(db_session, tenant_id, *, created_at, external_account_id="edi-crm-whatsapp"):
    message = Communication(
        tenant_id=tenant_id,
        channel="whatsapp",
        direction="inbound",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        whatsapp_chat_id="chat-1",
        whatsapp_identity_key="chat-1",
        message="hello",
        created_at=created_at,
    )
    db_session.add(message)
    db_session.commit()
    return message


def test_global_thread_version_is_none_when_nothing_exists(non_admin_client, db_session):
    response = non_admin_client.get("/api/communications/thread-version")

    assert response.status_code == 200
    assert response.json() == {
        "latest_at": None,
        "tenant_id": None,
        "tenant_name": None,
        "channel": None,
        "direction": None,
    }


def test_global_thread_version_reflects_tenant_update_without_messages(non_admin_client, db_session):
    tenant = create_tenant(db_session)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    tenant.updated_at = future
    db_session.commit()

    response = non_admin_client.get("/api/communications/thread-version")

    assert response.status_code == 200
    payload = response.json()
    assert _as_utc(datetime.fromisoformat(payload["latest_at"])) == future
    # A plain tenant-record update (no new message) carries no tenant/channel/direction info.
    assert payload["tenant_id"] is None
    assert payload["channel"] is None
    assert payload["direction"] is None


def test_tenant_thread_version_reflects_tenant_update_without_messages(non_admin_client, db_session):
    tenant = create_tenant(db_session)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    tenant.updated_at = future
    db_session.commit()

    response = non_admin_client.get(f"/api/communications/tenants/{tenant.id}/thread-version")

    assert response.status_code == 200
    assert _as_utc(datetime.fromisoformat(response.json()["latest_at"])) == future


def test_global_thread_version_reflects_latest_message_across_tenants(non_admin_client, db_session):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-1")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-2")

    older = datetime.now(timezone.utc) - timedelta(minutes=10)
    newer = datetime.now(timezone.utc)

    add_whatsapp_message(db_session, tenant_a.id, created_at=older)
    baseline = non_admin_client.get("/api/communications/thread-version").json()

    add_whatsapp_message(db_session, tenant_b.id, created_at=newer)
    updated = non_admin_client.get("/api/communications/thread-version").json()

    assert baseline["latest_at"] is not None
    assert updated["latest_at"] != baseline["latest_at"]


def test_global_thread_version_reports_tenant_and_channel_for_latest_message(non_admin_client, db_session):
    tenant = create_tenant(db_session, name="Jane Doe", booking_id="B-3")
    add_whatsapp_message(db_session, tenant.id, created_at=datetime.now(timezone.utc))

    response = non_admin_client.get("/api/communications/thread-version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == tenant.id
    assert payload["tenant_name"] == "Jane Doe"
    assert payload["channel"] == "whatsapp"
    assert payload["direction"] == "inbound"
