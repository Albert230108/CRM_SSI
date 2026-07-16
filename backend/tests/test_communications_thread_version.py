from datetime import datetime, timedelta, timezone

from app.models.communication import Communication
from app.models.tenant import Tenant


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


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


def test_global_thread_version_is_none_with_no_messages(non_admin_client, db_session):
    create_tenant(db_session)

    response = non_admin_client.get("/api/communications/thread-version")

    assert response.status_code == 200
    assert response.json() == {"latest_at": None}


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
