"""CRM_EMAIL links are the only authoritative email source.

Beds24's main guest email is whatever address the OTA forwarded - routinely an alias that
never reaches the guest and that matches unrelated mail. It is no longer written onto the
tenant by any sync path, and no matching path reads it.
"""

import base64

import app.api.gmail_integration as gmail_integration
from app.api.admin_sync import _update_tenant_from_beds24
from app.models.gmail_integration import GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_email_address import TenantEmailAddress
from app.services import beds24_sync


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _message(message_id: str, from_address: str, to_address: str) -> dict:
    return {
        "id": message_id,
        "internalDate": "1700000000000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": from_address},
                {"name": "To", "value": to_address},
                {"name": "Subject", "value": "Booking question"},
            ],
            "body": {"data": _encode("Hi there")},
        },
    }


def test_sync_all_does_not_overwrite_tenant_email_from_beds24(db_session):
    tenant = Tenant(name="Sync Tenant", booking_id="B-crm-email-1", email="old@example.com")
    db_session.add(tenant)
    db_session.commit()

    _update_tenant_from_beds24(db_session, tenant, {"id": "B-crm-email-1", "email": "ota-alias@example.com", "firstName": "Ana"})
    db_session.commit()
    db_session.refresh(tenant)

    assert tenant.first_name == "Ana"  # other fields still sync
    assert tenant.email == "old@example.com"


def test_beds24_sync_service_does_not_write_tenant_email(db_session, monkeypatch):
    import asyncio

    tenant = Tenant(name="Service Tenant", booking_id="B-crm-email-2", email="keep@example.com")
    db_session.add(tenant)
    db_session.commit()

    async def fake_fetch(booking_id):
        return {"id": booking_id, "email": "ota-alias@example.com", "firstName": "Bea", "status": 1}

    monkeypatch.setattr(beds24_sync, "fetch_booking_with_invoice", fake_fetch)
    asyncio.run(beds24_sync.sync_tenant_from_beds24_booking(db_session, "B-crm-email-2"))
    db_session.refresh(tenant)

    assert tenant.first_name == "Bea"
    assert tenant.email == "keep@example.com"


def test_sync_all_reconciles_crm_email_info_items(db_session):
    """A CRM_EMAIL added in Beds24 used to reach the CRM only via a live booking webhook."""
    tenant = Tenant(name="InfoItem Tenant", booking_id="B-crm-email-3")
    db_session.add(tenant)
    db_session.commit()

    _update_tenant_from_beds24(
        db_session,
        tenant,
        {
            "id": "B-crm-email-3",
            "firstName": "Cara",
            "infoItems": [{"id": 99, "code": "CRM_EMAIL", "text": "real-guest@example.com"}],
        },
    )
    db_session.commit()

    links = db_session.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant.id).all()
    assert [link.email for link in links] == ["real-guest@example.com"]


def test_inbound_mail_does_not_match_on_tenant_email(db_session):
    """The decisive case: a tenant with only a Beds24 main email must not capture mail."""
    account = GmailAccount(email_address="crm-account@example.com", is_active=True)
    tenant = Tenant(name="Unlinked Tenant", booking_id="B-crm-email-4", email="ota-alias@example.com")
    db_session.add_all([account, tenant])
    db_session.commit()

    thread = {
        "id": "thread-crm-email-1",
        "messages": [_message("msg-crm-1", "ota-alias@example.com", "crm-account@example.com")],
    }
    conversation = gmail_integration._upsert_thread(db_session, account, thread)
    db_session.commit()

    assert conversation is not None
    assert conversation.tenant_id is None
    assert (
        db_session.query(TenantConversationLink)
        .filter(TenantConversationLink.tenant_id == tenant.id)
        .count()
        == 0
    )


def test_inbound_mail_matches_on_an_active_crm_email_link(db_session):
    account = GmailAccount(email_address="crm-account-2@example.com", is_active=True)
    tenant = Tenant(name="Linked Tenant", booking_id="B-crm-email-5")
    db_session.add_all([account, tenant])
    db_session.commit()
    db_session.add(TenantEmailAddress(tenant_id=tenant.id, email="real-guest@example.com", is_active=True))
    db_session.commit()

    thread = {
        "id": "thread-crm-email-2",
        "messages": [_message("msg-crm-2", "real-guest@example.com", "crm-account-2@example.com")],
    }
    conversation = gmail_integration._upsert_thread(db_session, account, thread)
    db_session.commit()

    assert conversation is not None
    assert conversation.tenant_id == tenant.id


def test_full_sync_query_is_built_from_crm_email_links_only(db_session, monkeypatch):
    account = GmailAccount(email_address="crm-account-3@example.com", is_active=True)
    tenant = Tenant(name="Query Tenant", booking_id="B-crm-email-6", email="ota-alias@example.com")
    db_session.add_all([account, tenant])
    db_session.commit()
    db_session.add(TenantEmailAddress(tenant_id=tenant.id, email="real-guest@example.com", is_active=True))
    db_session.commit()

    captured: dict[str, str] = {}

    def fake_list(service, query):
        captured["query"] = query
        return []

    monkeypatch.setattr(gmail_integration, "_build_service_for_account", lambda acct: object())
    monkeypatch.setattr(gmail_integration, "_list_all_matching_threads", fake_list)

    gmail_integration._sync_gmail_account(db_session, account)

    assert '"real-guest@example.com"' in captured["query"]
    assert "ota-alias@example.com" not in captured["query"]
