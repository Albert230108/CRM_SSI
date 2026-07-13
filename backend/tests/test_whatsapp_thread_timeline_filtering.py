from datetime import datetime, timezone

from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.thread_timeline_service import build_tenant_thread_timeline


def create_tenant(db_session, name="Tenant A", booking_id="B-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def add_whatsapp_message(db_session, tenant_id, *, chat_id, text, external_account_id="edi-crm-whatsapp"):
    message = Communication(
        tenant_id=tenant_id,
        channel="whatsapp",
        direction="inbound",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        whatsapp_chat_id=chat_id,
        whatsapp_identity_key=chat_id,
        message=text,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(message)
    db_session.commit()
    return message


def _all_whatsapp_texts(timeline):
    texts = []
    for item in timeline.items:
        if item.type == "whatsapp_group":
            texts.extend(message.message for message in item.messages)
    return texts


def test_stray_chat_messages_are_excluded_once_a_manual_link_exists(db_session):
    tenant = create_tenant(db_session, booking_id="B-pollution")
    # Correctly matches the chat that will be manually linked.
    add_whatsapp_message(db_session, tenant.id, chat_id="326472368@lid", text="Real conversation message")
    # Stray message attributed to this tenant via looser phone-based matching from an unrelated chat.
    add_whatsapp_message(db_session, tenant.id, chat_id="999999999@lid", text="Unrelated stray message")

    db_session.add(
        TenantChannelEndpoint(
            tenant_id=tenant.id,
            channel_type="whatsapp",
            provider="whatsapp-service",
            external_account_id="edi-crm-whatsapp",
            external_chat_namespace="326472368@lid",
            source="manual",
            is_active=True,
        )
    )
    db_session.commit()

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    texts = _all_whatsapp_texts(timeline)

    assert "Real conversation message" in texts
    assert "Unrelated stray message" not in texts


def test_no_active_link_keeps_prior_unfiltered_behavior(db_session):
    tenant = create_tenant(db_session, booking_id="B-no-link")
    add_whatsapp_message(db_session, tenant.id, chat_id="111@lid", text="First message")
    add_whatsapp_message(db_session, tenant.id, chat_id="222@lid", text="Second message")

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    texts = _all_whatsapp_texts(timeline)

    assert "First message" in texts
    assert "Second message" in texts


def test_unlinked_manual_link_no_longer_filters(db_session):
    tenant = create_tenant(db_session, booking_id="B-unlinked-filter")
    add_whatsapp_message(db_session, tenant.id, chat_id="326472368@lid", text="Linked chat message")
    add_whatsapp_message(db_session, tenant.id, chat_id="999999999@lid", text="Other chat message")

    link = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="326472368@lid",
        source="manual",
        is_active=False,
        unlinked_at=datetime.now(timezone.utc),
    )
    db_session.add(link)
    db_session.commit()

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    texts = _all_whatsapp_texts(timeline)

    assert "Linked chat message" in texts
    assert "Other chat message" in texts


def test_bare_endpoint_without_chat_namespace_does_not_filter(db_session):
    """Bare endpoints (active but no external_chat_namespace) should not suppress messages.

    Scenario: After unlink -> reimport, if a bare endpoint exists with account but no chat namespace,
    the timeline filter should treat it as unlinked and show all messages for that account.
    """
    tenant = create_tenant(db_session, booking_id="B-bare-endpoint")
    add_whatsapp_message(db_session, tenant.id, chat_id="326472368@lid", text="First message")
    add_whatsapp_message(db_session, tenant.id, chat_id="999999999@lid", text="Second message")

    # Bare endpoint: active, has account_id, but no external_chat_namespace
    bare_endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace=None,
        source="system",
        is_active=True,
    )
    db_session.add(bare_endpoint)
    db_session.commit()

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    texts = _all_whatsapp_texts(timeline)

    # Both messages should be visible; bare endpoint should not filter
    assert "First message" in texts
    assert "Second message" in texts
