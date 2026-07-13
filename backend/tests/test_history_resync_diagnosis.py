"""
Diagnostic test to reproduce the WhatsApp history resync failure.

Scenario:
1. Create a tenant
2. Manually link a WhatsApp chat endpoint (with external_chat_namespace set)
3. Simulate 193 history backfill messages via webhook payloads (source: "history")
4. Verify:
   a) All messages are persisted to the database
   b) All messages have correct tenant_id and chat identity
   c) Timeline filter includes all messages
   d) Timeline API returns all messages
"""

from datetime import datetime, timezone, timedelta

from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.thread_timeline_service import build_tenant_thread_timeline, _load_tenant_whatsapp


def create_test_tenant(db_session, name="History Test Tenant", booking_id="B-history-test"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_manual_endpoint(db_session, tenant_id, external_account_id="edi-crm-whatsapp", external_chat_namespace="326472368@lid"):
    """Create a manually linked WhatsApp endpoint."""
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        external_chat_namespace=external_chat_namespace,
        source="manual",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


def simulate_history_webhook_import(
    db_session,
    tenant_id,
    num_messages=193,
    external_account_id="edi-crm-whatsapp",
    chat_id="326472368@lid",
    use_varied_formats=False,  # Alternate @lid/@c.us to simulate real backfill variation
):
    """Simulate what the webhook handler does: persist Communication rows from history payloads.

    This directly mimics lines 600-618 of whatsapp.py webhook handler.
    """
    base_id = "326472368"
    start_time = datetime.now(timezone.utc) - timedelta(days=30)

    for i in range(num_messages):
        # Alternate between @lid and @c.us to simulate variation seen in real backfill
        if use_varied_formats:
            chat_format = f"{base_id}@lid" if i % 2 == 0 else f"{base_id}@c.us"
        else:
            chat_format = chat_id

        # Direction alternates to simulate real conversation
        direction = "inbound" if i % 2 == 0 else "outbound"

        message = Communication(
            tenant_id=tenant_id,
            channel="whatsapp",
            direction=direction,
            provider="whatsapp-service",
            external_account_id=external_account_id,
            external_phone_id=None,
            external_chat_namespace=None,  # Webhook doesn't always set this
            whatsapp_chat_id=chat_format,
            whatsapp_identity_key=chat_format,
            whatsapp_normalized_phone=None,
            provider_message_id=f"msg-{i}",
            subject=None,
            message=f"History message {i}",
            created_at=start_time + timedelta(seconds=i),
        )
        db_session.add(message)

    db_session.commit()
    return num_messages


def test_history_resync_baseline_all_messages_persist(db_session):
    """Baseline: Verify all history messages are persisted with correct tenant."""
    tenant = create_test_tenant(db_session)
    external_account_id = "edi-crm-whatsapp"
    chat_id = "326472368@lid"

    # Step 1: Create manual link
    endpoint = create_manual_endpoint(db_session, tenant.id, external_account_id, chat_id)

    # Step 2: Import 193 messages simulating history backfill
    imported_count = simulate_history_webhook_import(
        db_session,
        tenant.id,
        num_messages=193,
        external_account_id=external_account_id,
        chat_id=chat_id,
        use_varied_formats=False,
    )

    # Step 3: Verify all messages persisted with correct tenant
    persisted = db_session.query(Communication).filter(
        Communication.tenant_id == tenant.id,
        Communication.channel == "whatsapp",
    ).all()

    print(f"[DIAGNOSTIC] Imported: {imported_count}, Persisted: {len(persisted)}")
    assert len(persisted) == 193, f"Expected 193 persisted messages, got {len(persisted)}"


def test_history_resync_identity_persistence(db_session):
    """Verify messages persist with correct account and chat identity fields."""
    tenant = create_test_tenant(db_session, booking_id="B-identity-persist")
    external_account_id = "edi-crm-whatsapp"
    chat_id = "326472368@lid"

    endpoint = create_manual_endpoint(db_session, tenant.id, external_account_id, chat_id)

    # Import messages
    simulate_history_webhook_import(
        db_session,
        tenant.id,
        num_messages=20,  # Small batch for inspection
        external_account_id=external_account_id,
        chat_id=chat_id,
    )

    # Verify identity fields
    persisted = db_session.query(Communication).filter(
        Communication.tenant_id == tenant.id,
        Communication.channel == "whatsapp",
    ).all()

    # Every message should have:
    # - correct external_account_id
    # - whatsapp_chat_id or whatsapp_identity_key matching the endpoint
    for msg in persisted:
        print(f"[DIAGNOSTIC] Message {msg.id}: account={msg.external_account_id}, chat_id={msg.whatsapp_chat_id}, identity_key={msg.whatsapp_identity_key}")
        assert msg.external_account_id == external_account_id
        assert msg.whatsapp_chat_id == chat_id
        assert msg.whatsapp_identity_key == chat_id


def test_history_resync_timeline_filter_passes(db_session):
    """Verify timeline filter includes all correctly persisted history messages."""
    tenant = create_test_tenant(db_session, booking_id="B-filter-pass")
    external_account_id = "edi-crm-whatsapp"
    chat_id = "326472368@lid"

    endpoint = create_manual_endpoint(db_session, tenant.id, external_account_id, chat_id)

    # Import 193 messages
    simulate_history_webhook_import(
        db_session,
        tenant.id,
        num_messages=193,
        external_account_id=external_account_id,
        chat_id=chat_id,
    )

    # Load what the timeline would retrieve
    filtered = _load_tenant_whatsapp(db_session, tenant.id)

    print(f"[DIAGNOSTIC] Before filter: 193, After filter: {len(filtered)}")
    assert len(filtered) == 193, f"Expected 193 messages after filter, got {len(filtered)}"


def test_history_resync_timeline_api_returns_messages(db_session):
    """Verify the full timeline API includes messages from history resync."""
    tenant = create_test_tenant(db_session, booking_id="B-timeline-api")
    external_account_id = "edi-crm-whatsapp"
    chat_id = "326472368@lid"

    endpoint = create_manual_endpoint(db_session, tenant.id, external_account_id, chat_id)

    # Import 193 messages
    simulate_history_webhook_import(
        db_session,
        tenant.id,
        num_messages=193,
        external_account_id=external_account_id,
        chat_id=chat_id,
    )

    # Build full timeline as frontend would call it
    timeline = build_tenant_thread_timeline(db_session, tenant.id)

    # Extract all WhatsApp messages from timeline
    whatsapp_messages = []
    for item in timeline.items:
        if item.type == "whatsapp_group":
            whatsapp_messages.extend(item.messages)
        elif item.type == "email_thread":
            for block in item.whatsapp_blocks:
                whatsapp_messages.extend(block.messages)

    print(f"[DIAGNOSTIC] Timeline returned: {len(whatsapp_messages)} WhatsApp messages")
    assert len(whatsapp_messages) == 193, f"Expected 193 messages in timeline, got {len(whatsapp_messages)}"


def test_history_resync_with_varied_identity_formats(db_session):
    """Test history sync where backfill uses mixed @lid/@c.us formats.

    Reproduces a real scenario where:
    - Manual link created with @lid format
    - Backfill returns messages with mixed @lid and @c.us for the same core ID
    """
    tenant = create_test_tenant(db_session, booking_id="B-mixed-formats")
    external_account_id = "edi-crm-whatsapp"
    base_id = "326472368"
    # Link uses @lid format
    linked_chat_id = f"{base_id}@lid"

    endpoint = create_manual_endpoint(db_session, tenant.id, external_account_id, linked_chat_id)

    # Import with varied formats
    simulate_history_webhook_import(
        db_session,
        tenant.id,
        num_messages=193,
        external_account_id=external_account_id,
        chat_id=linked_chat_id,
        use_varied_formats=True,  # Alternate @lid/@c.us
    )

    # All should be visible because they normalize to same core ID
    timeline = build_tenant_thread_timeline(db_session, tenant.id)

    whatsapp_messages = []
    for item in timeline.items:
        if item.type == "whatsapp_group":
            whatsapp_messages.extend(item.messages)

    print(f"[DIAGNOSTIC] With mixed formats: {len(whatsapp_messages)} messages visible")
    assert len(whatsapp_messages) == 193, f"Expected 193 messages with mixed formats, got {len(whatsapp_messages)}"


def test_history_resync_without_external_chat_namespace_in_payload(db_session):
    """Critical test: History payloads WITHOUT external_chat_namespace should still resolve.

    Reproduces the real-world scenario where WhatsApp service sends:
    - external_account_id: YES
    - whatsapp_chat_id: YES
    - external_chat_namespace: NO (this is what's missing in real backfill!)

    Resolution should use normalized_chat_endpoint fallback strategy.
    """
    from app.webhooks.whatsapp import WhatsAppWebhookResponse
    from app.services.tenant_channel_resolver import resolve_tenant_for_inbound_channel

    tenant = create_test_tenant(db_session, booking_id="B-no-external-namespace")
    external_account_id = "edi-crm-whatsapp"
    chat_id = "326472368@lid"

    # Create manual endpoint
    endpoint = create_manual_endpoint(db_session, tenant.id, external_account_id, chat_id)

    # Simulate history webhook payload as it actually comes from WhatsApp service:
    # - NO external_chat_namespace
    # - YES whatsapp_chat_id (but in different format sometimes)
    history_payload = {
        "provider": "whatsapp-service",
        "external_account_id": external_account_id,
        "whatsapp_chat_id": "326472368@c.us",  # Different format from endpoint's @lid
        # NOTE: No external_chat_namespace!
        "direction": "inbound",
        "source": "history",
        "sender": "123456789",
        "message": "Test history message",
        "timestamp": 1234567890,
    }

    # Test resolver can find the tenant despite missing external_chat_namespace
    resolved = resolve_tenant_for_inbound_channel(db_session, history_payload, {}, {})

    print(f"[DIAGNOSTIC] History without external_namespace: strategy={resolved.strategy}, resolved_tenant={resolved.tenant.id if resolved.tenant else None}")
    assert resolved.tenant is not None, f"Should resolve tenant via normalized_chat_endpoint, got: {resolved.unresolved_reason}"
    assert resolved.tenant.id == tenant.id
    assert resolved.strategy == "normalized_chat_endpoint"
