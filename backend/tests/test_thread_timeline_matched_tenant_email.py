from datetime import datetime, timezone

from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_email_address import TenantEmailAddress
from app.models.tenant_conversation_link import TenantConversationLink
from app.services.thread_timeline_service import build_tenant_thread_timeline


def _make_conversation(db_session, tenant, provider_thread_id):
    conversation = Conversation(
        provider="gmail",
        provider_thread_id=provider_thread_id,
        tenant_id=tenant.id,
        subject="Re: Booking",
        last_message_at=datetime.now(timezone.utc),
    )
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id=f"msg-{provider_thread_id}",
            direction="inbound",
            sender_email="guest@example.com",
            recipient_email="info@shortstayinn.com",
            subject="Re: Booking",
            body="Hi there",
            sent_at=datetime.now(timezone.utc),
            raw_payload={"gmail": {"id": f"msg-{provider_thread_id}"}},
        )
    )
    db_session.commit()
    return conversation


def test_matched_tenant_email_surfaces_from_conversation_link(db_session):
    tenant = Tenant(name="Tenant A", email="primary@example.com", booking_id="B-matched-email-1")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    conversation = _make_conversation(db_session, tenant, "thread-matched-1")
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, matched_email="secondary@example.com"))
    db_session.commit()

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    thread_item = next(item for item in timeline.items if item.type == "email_thread")

    assert thread_item.matched_tenant_email == "secondary@example.com"


def test_matched_tenant_email_falls_back_to_linked_email_when_unrecorded(db_session):
    """A link with no recorded matched_email displays the tenant's CRM_EMAIL address."""
    tenant = Tenant(name="Tenant B", booking_id="B-matched-email-2")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    db_session.add(TenantEmailAddress(tenant_id=tenant.id, email="primary@example.com", is_active=True))
    db_session.commit()

    conversation = _make_conversation(db_session, tenant, "thread-matched-2")
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, matched_email=None))
    db_session.commit()

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    thread_item = next(item for item in timeline.items if item.type == "email_thread")

    assert thread_item.matched_tenant_email == "primary@example.com"


def test_hidden_thread_is_excluded_from_timeline(db_session):
    tenant = Tenant(name="Tenant C", email="shared@example.com", booking_id="B-matched-email-3")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    conversation = _make_conversation(db_session, tenant, "thread-matched-3")
    db_session.add(
        TenantConversationLink(tenant_id=tenant.id, conversation_id=conversation.id, matched_email="shared@example.com", is_visible=False)
    )
    db_session.commit()

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    thread_items = [item for item in timeline.items if item.type == "email_thread"]

    assert thread_items == []
