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


def test_duplicate_capture_of_same_message_seconds_apart_upgrades_placeholder(db_session):
    # Regression: sending a message from the CRM persists it immediately (backend wall-clock
    # created_at, often with a real provider_message_id already). The message_create listener
    # also observes that same physical WhatsApp message a moment later, sometimes without a
    # provider_message_id, and reports WhatsApp's own timestamp for it - which can differ from
    # the first capture's created_at by a few seconds. Requiring exact created_at equality
    # (rather than a tolerance window) caused this second capture to create a duplicate row
    # instead of being recognized as the same message, showing the message twice in the UI.
    tenant = create_tenant(db_session, name="Tenant Outbound Persist D", booking_id="B-outbound-persist-d")

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
        message="Hi Giacomo, here are the next steps",
        created_at=datetime(2026, 7, 17, 14, 42, 0, tzinfo=timezone.utc),
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
        message="Hi Giacomo, here are the next steps",
        created_at=datetime(2026, 7, 17, 14, 42, 4, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert second.persistence_state == "deduped"
    assert second.communication.id == first.communication.id


def test_duplicate_capture_of_the_same_physical_message_upgrades_placeholder(db_session):
    # The original "upgrade a pending placeholder" behavior must still work when the same
    # physical WhatsApp message is reported twice without a provider_message_id (e.g. captured
    # once via the explicit send path and once via the message_create listener). Both captures
    # share WhatsApp's own reported timestamp for that message, so created_at is identical.
    tenant = create_tenant(db_session, name="Tenant Outbound Persist B", booking_id="B-outbound-persist-b")
    shared_created_at = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)

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
        created_at=shared_created_at,
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
        created_at=shared_created_at,
    )
    db_session.commit()

    assert second.persistence_state == "deduped"
    assert second.communication.id == first.communication.id


def test_two_distinct_sends_with_similar_text_and_no_provider_message_id_both_appear(db_session):
    # Regression: two separate messages sent moments apart from another linked device, with
    # similar/identical text, previously collided on the text-only fallback match and the second
    # silently overwrote the first (same bug class as the distinct-text case, but exposed here
    # because the text happens to match too). Requiring the WhatsApp-reported timestamp to also
    # match keeps these as two separate rows since they were sent at different times.
    tenant = create_tenant(db_session, name="Tenant Outbound Persist C", booking_id="B-outbound-persist-c")

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
        message="Hey",
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
        message="Hey",
        created_at=datetime(2026, 7, 17, 10, 3, 0, tzinfo=timezone.utc),
    )
    db_session.commit()

    assert second.persistence_state == "created"
    assert second.communication.id != first.communication.id
    assert first.communication.created_at.replace(tzinfo=timezone.utc) == datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)
    assert second.communication.created_at.replace(tzinfo=timezone.utc) == datetime(2026, 7, 17, 10, 3, 0, tzinfo=timezone.utc)
