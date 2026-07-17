from datetime import datetime, timezone

from app.models.tenant import Tenant
from app.services.whatsapp_outbound_persistence import persist_whatsapp_outbound_communication


def create_tenant(db_session, name="Tenant Outbound Persist", booking_id="B-outbound-persist"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_second_distinct_outbound_message_without_provider_message_id_creates_new_row(db_session):
    # Regression: live-captured outbound messages (e.g. sent from another linked device) that
    # never received a provider_message_id previously matched the identity-key fallback and
    # silently overwrote the most recent placeholder row's text instead of creating a new
    # Communication. A second, genuinely different message must create its own row.
    tenant = create_tenant(db_session)

    first = persist_whatsapp_outbound_communication(
        db_session,
        tenant_id=tenant.id,
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_phone_id=None,
        external_chat_namespace=None,
        whatsapp_chat_id="155066153590862@lid",
        whatsapp_identity_key="155066153590862@lid",
        whatsapp_normalized_phone=None,
        provider_message_id=None,
        subject=None,
        message="First message from another device",
        created_at=datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc),
    )
    db_session.commit()
    assert first.persistence_state == "created"

    second = persist_whatsapp_outbound_communication(
        db_session,
        tenant_id=tenant.id,
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_phone_id=None,
        external_chat_namespace=None,
        whatsapp_chat_id="155066153590862@lid",
        whatsapp_identity_key="155066153590862@lid",
        whatsapp_normalized_phone=None,
        provider_message_id=None,
        subject=None,
        message="Second, different message from another device",
        created_at=datetime(2026, 7, 17, 10, 5, 0, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert second.persistence_state == "created"
    assert second.communication.id != first.communication.id
    assert first.communication.message == "First message from another device"
    assert second.communication.message == "Second, different message from another device"


def test_repeated_identical_outbound_message_without_provider_message_id_upgrades_placeholder(db_session):
    # The original "upgrade a pending placeholder" behavior must still work when the same
    # message text arrives again without a provider_message_id (e.g. a duplicate live capture
    # of the same send before WhatsApp confirms delivery).
    tenant = create_tenant(db_session, name="Tenant Outbound Persist B", booking_id="B-outbound-persist-b")

    first = persist_whatsapp_outbound_communication(
        db_session,
        tenant_id=tenant.id,
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_phone_id=None,
        external_chat_namespace=None,
        whatsapp_chat_id="155066153590862@lid",
        whatsapp_identity_key="155066153590862@lid",
        whatsapp_normalized_phone=None,
        provider_message_id=None,
        subject=None,
        message="Same text",
        created_at=datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc),
    )
    db_session.commit()

    second = persist_whatsapp_outbound_communication(
        db_session,
        tenant_id=tenant.id,
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_phone_id=None,
        external_chat_namespace=None,
        whatsapp_chat_id="155066153590862@lid",
        whatsapp_identity_key="155066153590862@lid",
        whatsapp_normalized_phone=None,
        provider_message_id=None,
        subject=None,
        message="Same text",
        created_at=datetime(2026, 7, 17, 10, 0, 5, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert second.persistence_state == "deduped"
    assert second.communication.id == first.communication.id
