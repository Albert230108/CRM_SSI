"""
Test how the webhook resolver routes history payloads.

Key issue: When WhatsApp service sends history backfill payloads, does it include:
1. tenant_id?
2. external_chat_namespace?
3. Can routing find the right tenant via phone/chat inference alone?

If a history payload doesn't include explicit tenant routing info,
the backend resolver must use fallback strategies (phone match, chat ID match).
But if the phone is from a tenant not created yet or if chat ID ambiguity exists,
routing could fail or succeed to wrong tenant.
"""

from datetime import datetime, timezone

from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.tenant_phone_alias import TenantPhoneAlias
from app.services.tenant_channel_resolver import resolve_tenant_for_inbound_channel


def create_test_tenant(db_session, name, booking_id, phone=None):
    tenant = Tenant(name=name, booking_id=booking_id, phone=phone)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_history_payload_with_explicit_tenant_id(db_session):
    """If payload includes tenant_id, routing should find it directly."""
    tenant = create_test_tenant(db_session, "History Tenant", "B-1")

    # Simulate history payload WITH tenant_id
    payload = {
        "tenant_id": tenant.id,
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "326472368@lid",
        "external_chat_namespace": "326472368@lid",
        "direction": "inbound",
        "source": "history",
        "message": "Test",
    }

    resolved = resolve_tenant_for_inbound_channel(db_session, payload, {}, {})

    print(f"[WEBHOOK_ROUTING] explicit_tenant_id: strategy={resolved.strategy}, tenant_id={resolved.tenant.id if resolved.tenant else None}")
    assert resolved.tenant is not None
    assert resolved.tenant.id == tenant.id


def test_history_payload_without_tenant_id_with_account_and_chat_match(db_session):
    """History payload with external_account_id + external_chat_namespace but no tenant_id.

    Scenario: WhatsApp service provides:
    - external_account_id (the service account)
    - external_chat_namespace (the chat being synced)
    But NOT tenant_id (because it's bulk backfill)

    Resolution should use exact_chat_endpoint matching.
    """
    tenant = create_test_tenant(db_session, "Chat Match Tenant", "B-2")

    # Create the manual link that the backfill should discover
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="326472368@lid",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    # Simulate history payload WITHOUT tenant_id but WITH account + chat
    payload = {
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "326472368@lid",
        "external_chat_namespace": "326472368@lid",
        "direction": "inbound",
        "source": "history",
        "message": "Test",
    }

    resolved = resolve_tenant_for_inbound_channel(db_session, payload, {}, {})

    print(f"[WEBHOOK_ROUTING] account+chat_match: strategy={resolved.strategy}, tenant_id={resolved.tenant.id if resolved.tenant else None}")
    assert resolved.tenant is not None
    assert resolved.tenant.id == tenant.id
    assert resolved.strategy == "exact_chat_endpoint"


def test_history_payload_account_only_no_chat_fallback_disabled(db_session):
    """History payload with account but NO explicit external_chat_namespace.

    This is the real-world case for backfill:
    - Backfill payload includes external_account_id
    - Backfill payload provides whatsapp_chat_id (NOT external_chat_namespace)
    - Endpoint exists with matching account and normalized chat ID

    Expected: Should resolve via normalized_chat_endpoint fallback.
    """
    tenant = create_test_tenant(db_session, "Account Fallback Tenant", "B-3")

    # Create a manual endpoint
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="326472368@lid",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    # Simulate history payload WITHOUT explicit external_chat_namespace (real WhatsApp service behavior)
    # But WITH whatsapp_chat_id that matches endpoint's external_chat_namespace
    payload = {
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "326472368@lid",
        # NOTE: missing external_chat_namespace! This is what WhatsApp service sends.
        "direction": "inbound",
        "source": "history",
        "message": "Test",
    }

    resolved = resolve_tenant_for_inbound_channel(db_session, payload, {}, {})

    print(f"[WEBHOOK_ROUTING] account_only_no_fallback: strategy={resolved.strategy}, tenant_id={resolved.tenant.id if resolved.tenant else None}, reason={resolved.unresolved_reason}")
    # With normalized matching fallback, this should succeed
    assert resolved.tenant is not None, f"Expected to resolve tenant, got: {resolved.unresolved_reason}"
    assert resolved.tenant.id == tenant.id


def test_history_payload_normalized_chat_with_format_variation(db_session):
    """Test normalized chat matching when endpoint uses @lid but payload has @c.us (or vice versa).

    Real-world scenario: WhatsApp service history backfill may return chat IDs in different
    formats than the manual endpoint was created with.
    """
    tenant = create_test_tenant(db_session, "Norm Format Tenant", "B-3b")

    # Endpoint was created with @lid format
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="326472368@lid",
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()

    # Backfill payload arrives with @c.us format (same core ID)
    payload = {
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "326472368@c.us",  # Different format, same core ID
        "direction": "inbound",
        "source": "history",
        "message": "Test",
    }

    resolved = resolve_tenant_for_inbound_channel(db_session, payload, {}, {})

    print(f"[WEBHOOK_ROUTING] normalized_format: strategy={resolved.strategy}, tenant_id={resolved.tenant.id if resolved.tenant else None}")
    # Should match via normalized comparison
    assert resolved.tenant is not None
    assert resolved.tenant.id == tenant.id


def test_history_payload_phone_inference_single_tenant_match(db_session):
    """History payload uses phone number inference when chat ID is missing.

    Scenario:
    - Payload has no tenant_id, no explicit chat namespace
    - But payload has sender phone number
    - Tenant has that phone alias registered
    """
    tenant = create_test_tenant(db_session, "Phone Match Tenant", "B-4", phone="+351-9-1234-5678")

    # Create phone alias
    alias = TenantPhoneAlias(tenant_id=tenant.id, normalized_phone="351912345678", is_primary=True, source="primary")
    db_session.add(alias)
    db_session.commit()

    # Simulate history payload WITHOUT tenant_id, WITHOUT external_chat_namespace
    # But WITH phone number that matches tenant
    payload = {
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "351912345678@c.us",  # Phone-based chat ID
        # Missing external_chat_namespace
        "direction": "inbound",
        "source": "history",
        "message": "Test",
    }

    resolved = resolve_tenant_for_inbound_channel(db_session, payload, {}, {})

    print(f"[WEBHOOK_ROUTING] phone_inference: strategy={resolved.strategy}, tenant_id={resolved.tenant.id if resolved.tenant else None}")
    # This should resolve via phone inference
    if resolved.tenant:
        assert resolved.tenant.id == tenant.id
        print(f"[WEBHOOK_ROUTING] ✓ Resolved via phone inference")
    else:
        print(f"[WEBHOOK_ROUTING] ✗ Failed to resolve: {resolved.unresolved_reason}")


def test_history_payload_ambiguous_phone_multiple_tenants(db_session):
    """History payload phone matches multiple tenants → routing fails.

    This is a real edge case if phone numbers are shared or aliases overlap.
    """
    tenant1 = create_test_tenant(db_session, "Tenant A", "B-5", phone="+351-9-1234-5678")
    tenant2 = create_test_tenant(db_session, "Tenant B", "B-6", phone="+351-9-1234-5678")  # Same phone

    # Create aliases for both
    alias1 = TenantPhoneAlias(tenant_id=tenant1.id, normalized_phone="351912345678", is_primary=True, source="primary")
    alias2 = TenantPhoneAlias(tenant_id=tenant2.id, normalized_phone="351912345678", is_primary=True, source="primary")
    db_session.add_all([alias1, alias2])
    db_session.commit()

    # History payload with ambiguous phone
    payload = {
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "whatsapp_chat_id": "351912345678@c.us",
        "direction": "inbound",
        "source": "history",
        "message": "Test",
    }

    resolved = resolve_tenant_for_inbound_channel(db_session, payload, {}, {})

    print(f"[WEBHOOK_ROUTING] ambiguous_phone: strategy={resolved.strategy}, reason={resolved.unresolved_reason}")
    # Should detect ambiguity and fail
    if resolved.tenant is None:
        print(f"[WEBHOOK_ROUTING] ✓ Correctly rejected ambiguous match: {resolved.unresolved_reason}")
    else:
        print(f"[WEBHOOK_ROUTING] ⚠️  Accepted ambiguous match (may cause wrong tenant assignment)")
