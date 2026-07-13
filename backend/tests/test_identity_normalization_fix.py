"""
Test for WhatsApp identity normalization fix.

This test verifies that the timeline filtering correctly handles @lid and @c.us
identity format variations, ensuring all messages from the same chat are visible
regardless of which format was used in the stored data or the manual link.
"""
from datetime import datetime, timezone

from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.services.thread_timeline_service import (
    _normalize_identity_for_comparison,
    _communication_matches_chat_identity,
    build_tenant_thread_timeline,
)


def test_normalize_identity_strips_lid_suffix():
    """Test that @lid suffix is stripped for normalization."""
    assert _normalize_identity_for_comparison("326472368@lid") == "326472368"
    assert _normalize_identity_for_comparison("326472368@LID") == "326472368"


def test_normalize_identity_strips_cus_suffix():
    """Test that @c.us suffix is stripped for normalization."""
    assert _normalize_identity_for_comparison("326472368@c.us") == "326472368"
    assert _normalize_identity_for_comparison("326472368@C.US") == "326472368"


def test_normalize_identity_strips_gus_suffix():
    """Test that @g.us suffix is stripped for normalization."""
    assert _normalize_identity_for_comparison("326472368@g.us") == "326472368"


def test_normalize_identity_handles_none():
    """Test that None returns None."""
    assert _normalize_identity_for_comparison(None) is None


def test_normalize_identity_handles_empty_string():
    """Test that empty string returns None."""
    assert _normalize_identity_for_comparison("") is None
    assert _normalize_identity_for_comparison("   ") is None


def test_communication_matches_with_equivalent_formats():
    """Test that communication matching works with equivalent identity formats."""
    comm = Communication(
        tenant_id=1,
        channel="whatsapp",
        direction="inbound",
        message="Test",
        whatsapp_chat_id="326472368@lid",
        whatsapp_identity_key="326472368@lid",
    )

    # Should match with @c.us format
    assert _communication_matches_chat_identity(comm, "326472368@c.us")
    # Should match with original @lid format
    assert _communication_matches_chat_identity(comm, "326472368@lid")
    # Should NOT match different ID
    assert not _communication_matches_chat_identity(comm, "999999999@lid")


def test_large_history_with_mixed_formats_timeline(db_session):
    """Integration test: 194 messages with mixed formats show all in timeline."""
    tenant = Tenant(name="Tenant History Mixed", booking_id="B-history-mixed")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    base_id = "326472368"
    messages_count = 194

    # Add 194 messages with alternating identity formats
    for i in range(messages_count):
        chat_format = f"{base_id}@lid" if i % 2 == 0 else f"{base_id}@c.us"
        message = Communication(
            tenant_id=tenant.id,
            channel="whatsapp",
            direction="inbound",
            provider="whatsapp-service",
            external_account_id="edi-crm-whatsapp",
            whatsapp_chat_id=chat_format,
            whatsapp_identity_key=chat_format,
            message=f"Message {i}",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(message)
    db_session.commit()

    # Create manual link with @lid format
    db_session.add(
        TenantChannelEndpoint(
            tenant_id=tenant.id,
            channel_type="whatsapp",
            provider="whatsapp-service",
            external_account_id="edi-crm-whatsapp",
            external_chat_namespace=f"{base_id}@lid",
            source="manual",
            is_active=True,
        )
    )
    db_session.commit()

    # Build timeline
    timeline = build_tenant_thread_timeline(db_session, tenant.id)

    # Extract all message texts
    messages = []
    for item in timeline.items:
        if item.type == "whatsapp_group":
            messages.extend(message.message for message in item.messages)

    # All 194 messages should be visible
    assert len(messages) == messages_count, f"Expected {messages_count} messages, got {len(messages)}"
    for i in range(messages_count):
        assert f"Message {i}" in messages
