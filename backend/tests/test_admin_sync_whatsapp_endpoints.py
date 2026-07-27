"""
Test admin sync's new per-endpoint WhatsApp history delegation.

Verifies that main sync now delegates to individual linked-chat
resync operations instead of generic account-level backfill.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.communication import Communication
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint


def create_tenant(db_session, name="Admin Sync Test", booking_id="B-admin-sync"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_whatsapp_endpoint(
    db_session,
    tenant_id,
    external_account_id="edi-crm-whatsapp",
    external_chat_namespace="326472368@lid",
    is_active=True,
):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        external_chat_namespace=external_chat_namespace,
        is_active=is_active,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


@pytest.mark.asyncio
async def test_admin_sync_delegates_to_per_endpoint_backfill(db_session):
    """Verify admin sync calls per-endpoint resync for each linked chat.

    Scenario:
    - Tenant with one manually linked WhatsApp chat endpoint
    - Admin calls /admin/sync-all
    - Expected: Delegates to per-endpoint sync for that specific chat
    """
    from app.api.admin_sync import _sync_whatsapp_linked_endpoints

    tenant = create_tenant(db_session, booking_id="B-admin-endpoint-test")
    endpoint = create_whatsapp_endpoint(
        db_session,
        tenant.id,
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="326472368@lid",
    )

    # Mock the WhatsApp service response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "fetched": 193,
        "imported": 193,
        "deduped": 0,
        "failed": 0,
        "inbound": 97,
        "outbound": 96,
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await _sync_whatsapp_linked_endpoints(db_session)

    # Verify sync was triggered for the endpoint
    assert result["synced_endpoints"] == 1
    assert result["total_imported"] == 193
    assert len(result["results"]) == 1

    endpoint_result = result["results"][0]
    assert endpoint_result["endpoint_id"] == endpoint.id
    assert endpoint_result["tenant_id"] == tenant.id
    assert endpoint_result["chat_id"] == "326472368@lid"
    assert endpoint_result["imported"] == 193
    assert endpoint_result["fetched"] == 193

    # Verify API was called with correct parameters
    call_args = mock_client.post.call_args
    assert call_args[0][0].endswith("/admin/backfill")  # URL
    assert call_args[1]["json"]["chatId"] == "326472368@lid"  # Specific chat


@pytest.mark.asyncio
async def test_admin_sync_multiple_endpoints(db_session):
    """Verify admin sync handles multiple endpoints per account/tenant."""
    from app.api.admin_sync import _sync_whatsapp_linked_endpoints

    tenant = create_tenant(db_session, booking_id="B-multi-endpoint")
    endpoint1 = create_whatsapp_endpoint(
        db_session, tenant.id, external_chat_namespace="111111111@lid"
    )
    endpoint2 = create_whatsapp_endpoint(
        db_session,
        tenant.id,
        external_account_id="second-account",
        external_chat_namespace="222222222@c.us",
    )

    # Mock responses for each endpoint
    responses = [
        {
            "fetched": 50,
            "imported": 50,
            "deduped": 0,
            "failed": 0,
            "inbound": 25,
            "outbound": 25,
        },
        {
            "fetched": 100,
            "imported": 100,
            "deduped": 0,
            "failed": 0,
            "inbound": 50,
            "outbound": 50,
        },
    ]

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        # Return different responses for each call
        mock_client.post.side_effect = [
            MagicMock(json=lambda: responses[0]),
            MagicMock(json=lambda: responses[1]),
        ]
        mock_client_class.return_value = mock_client

        result = await _sync_whatsapp_linked_endpoints(db_session)

    # Verify both endpoints were synced
    assert result["synced_endpoints"] == 2
    assert result["total_imported"] == 150  # 50 + 100
    assert len(result["results"]) == 2

    # Verify correct aggregation
    total_fetched = sum(r["fetched"] for r in result["results"])
    total_imported = sum(r["imported"] for r in result["results"])
    assert total_fetched == 150
    assert total_imported == 150


@pytest.mark.asyncio
async def test_admin_sync_skips_inactive_endpoints(db_session):
    """Verify sync only includes active endpoints with manual links."""
    from app.api.admin_sync import _sync_whatsapp_linked_endpoints

    tenant = create_tenant(db_session, booking_id="B-inactive-endpoint")
    # Active endpoint
    active = create_whatsapp_endpoint(db_session, tenant.id, is_active=True)
    # Inactive endpoint
    inactive = create_whatsapp_endpoint(
        db_session,
        tenant.id,
        external_chat_namespace="999999999@lid",
        is_active=False,
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "fetched": 10,
        "imported": 10,
        "deduped": 0,
        "failed": 0,
        "inbound": 5,
        "outbound": 5,
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await _sync_whatsapp_linked_endpoints(db_session)

    # Only active endpoint should be synced
    assert result["synced_endpoints"] == 1
    assert result["results"][0]["endpoint_id"] == active.id
    # Verify only one POST call was made
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_admin_sync_skips_bare_endpoints(db_session):
    """Verify sync skips endpoints without external_chat_namespace.

    Bare endpoints (account linked but no specific chat) are not synced
    at endpoint level; they require manual linking first.
    """
    from app.api.admin_sync import _sync_whatsapp_linked_endpoints

    tenant = create_tenant(db_session, booking_id="B-bare-endpoint")
    # Bare endpoint: no external_chat_namespace
    bare_endpoint = TenantChannelEndpoint(
        tenant_id=tenant.id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace=None,  # No specific chat
        is_active=True,
    )
    db_session.add(bare_endpoint)
    db_session.commit()

    with patch("httpx.AsyncClient") as mock_client_class:
        result = await _sync_whatsapp_linked_endpoints(db_session)

    # No endpoints should be synced
    assert result["synced_endpoints"] == 0
    assert len(result["results"]) == 0


@pytest.mark.asyncio
async def test_admin_sync_delegates_to_resync_whatsapp_chat_service(db_session):
    """Bulk sync must call the exact same resync_whatsapp_chat() service function that the
    Manage Chats "Resync full history" button uses, so it honors per-account URL routing
    (WHATSAPP_SERVICE_URL_MAP) instead of a single global WHATSAPP_SERVICE_URL -- previously
    it built its own httpx request straight from WHATSAPP_SERVICE_URL, which sent every
    linked chat to the same instance regardless of which WhatsApp account it belonged to."""
    from app.api.admin_sync import _sync_whatsapp_linked_endpoints

    tenant = create_tenant(db_session, booking_id="B-delegate-service")
    endpoint = create_whatsapp_endpoint(
        db_session,
        tenant.id,
        external_account_id="second-account",
        external_chat_namespace="326472368@lid",
    )

    with patch(
        "app.api.admin_sync.resync_whatsapp_chat",
        new=AsyncMock(return_value={"ok": True, "fetched": 5, "imported": 5, "deduped": 0, "failed": 0}),
    ) as mocked_resync:
        result = await _sync_whatsapp_linked_endpoints(db_session)

    mocked_resync.assert_awaited_once_with("second-account", "326472368@lid")
    assert result["synced_endpoints"] == 1
    assert result["results"][0]["endpoint_id"] == endpoint.id
    assert result["total_imported"] == 5


@pytest.mark.asyncio
async def test_admin_sync_reconciles_existing_message_namespace(db_session):
    """After a bulk resync, existing Communication rows for that chat must have their
    external_chat_namespace backfilled to match the link, mirroring the reconciliation the
    per-chat Manage Chats resync endpoint performs -- otherwise messages imported before this
    fix (or without a namespace set) silently stay excluded from timeline filtering."""
    from app.api.admin_sync import _sync_whatsapp_linked_endpoints

    tenant = create_tenant(db_session, booking_id="B-reconcile")
    create_whatsapp_endpoint(
        db_session,
        tenant.id,
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace="326472368@lid",
    )

    stale_message = Communication(
        tenant_id=tenant.id,
        channel="whatsapp",
        direction="inbound",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        whatsapp_chat_id="326472368@lid",
        whatsapp_identity_key="326472368@lid",
        external_chat_namespace=None,
        message="hello",
    )
    db_session.add(stale_message)
    db_session.commit()
    db_session.refresh(stale_message)

    with patch(
        "app.api.admin_sync.resync_whatsapp_chat",
        new=AsyncMock(return_value={"ok": True, "fetched": 1, "imported": 1, "deduped": 0, "failed": 0}),
    ):
        await _sync_whatsapp_linked_endpoints(db_session)

    db_session.refresh(stale_message)
    assert stale_message.external_chat_namespace == "326472368@lid"


@pytest.mark.asyncio
async def test_admin_sync_handles_service_errors(db_session):
    """Verify sync continues on service errors and reports them."""
    from app.api.admin_sync import _sync_whatsapp_linked_endpoints

    tenant = create_tenant(db_session, booking_id="B-service-error")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = Exception("Service timeout")
        mock_client_class.return_value = mock_client

        result = await _sync_whatsapp_linked_endpoints(db_session)

    # Endpoint sync failed but reported
    assert result["synced_endpoints"] == 0
    assert len(result["results"]) == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["endpoint_id"] == endpoint.id
    assert "Service timeout" in result["errors"][0]["error"]
