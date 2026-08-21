"""Regression tests for handle_tenant_email_change.

Beds24 booking resyncs (scheduled sync, webhooks, admin sync-all) overwrite Tenant.email
directly with whatever the booking currently has -- unlike the manual "linked emails" UI,
there's no human confirmation step. This must still disconnect the old email's Gmail
conversations (unlink if shared with another tenant, delete otherwise) and kick off a Gmail
resync for the new address, mirroring the manual unlink/link endpoints.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.services.tenant_email_change import handle_tenant_email_change

NO_OP_GMAIL_SYNC_RESULT = {"accounts_checked": 0, "accounts_failed": 0, "conversations_matched": 0}


def call_with_running_loop(db_session, tenant, old_email, new_email):
    """handle_tenant_email_change schedules the Gmail resync via asyncio.create_task, which
    needs a running loop (true of every real caller: webhook handler, admin sync-all job). Give
    the direct unit-test call the same thing, and pump the loop briefly so the scheduled task
    (and the thread it hands the mocked sync call to) actually runs before the loop closes.
    """

    async def _run():
        handle_tenant_email_change(db_session, tenant, old_email, new_email)
        await asyncio.sleep(0.2)

    asyncio.run(_run())


def create_tenant(db_session, name="Tenant A", booking_id="B-1", email=None):
    tenant = Tenant(name=name, booking_id=booking_id, email=email)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def make_conversation_matched_to_email(db_session, tenant_id, email, provider_thread_id):
    conversation = Conversation(provider="gmail", provider_thread_id=provider_thread_id, tenant_id=tenant_id, subject="Re: Booking")
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)
    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id=f"msg-{provider_thread_id}",
            direction="inbound",
            sender_email=email,
            recipient_email="info@shortstayinn.com",
            subject="Re: Booking",
            body="Hi",
            sent_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(TenantConversationLink(tenant_id=tenant_id, conversation_id=conversation.id, matched_email=email))
    db_session.commit()
    return conversation.id


@patch("app.services.tenant_email_change.sync_email_across_gmail_accounts", return_value=NO_OP_GMAIL_SYNC_RESULT)
def test_email_change_deletes_unshared_old_conversation_and_starts_resync(mock_sync, db_session):
    tenant = create_tenant(db_session, booking_id="B-change-1", email="old@example.com")
    conversation_id = make_conversation_matched_to_email(db_session, tenant.id, "old@example.com", "thread-change-1")

    call_with_running_loop(db_session, tenant, "old@example.com", "new@example.com")
    db_session.commit()

    assert db_session.query(Conversation).filter(Conversation.id == conversation_id).first() is None
    assert db_session.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation_id).count() == 0
    mock_sync.assert_called_once_with("new@example.com")


@patch("app.services.tenant_email_change.sync_email_across_gmail_accounts", return_value=NO_OP_GMAIL_SYNC_RESULT)
def test_email_change_keeps_conversation_shared_with_another_tenant(mock_sync, db_session):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-change-shared-a", email="shared@example.com")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-change-shared-b")

    conversation_id = make_conversation_matched_to_email(db_session, tenant_a.id, "shared@example.com", "thread-change-shared")
    db_session.add(TenantConversationLink(tenant_id=tenant_b.id, conversation_id=conversation_id, matched_email="shared@example.com"))
    db_session.commit()

    call_with_running_loop(db_session, tenant_a, "shared@example.com", "new@example.com")
    db_session.commit()

    assert db_session.query(Conversation).filter(Conversation.id == conversation_id).first() is not None
    tenant_a_link = (
        db_session.query(TenantConversationLink)
        .filter(TenantConversationLink.tenant_id == tenant_a.id, TenantConversationLink.conversation_id == conversation_id)
        .first()
    )
    tenant_b_link = (
        db_session.query(TenantConversationLink)
        .filter(TenantConversationLink.tenant_id == tenant_b.id, TenantConversationLink.conversation_id == conversation_id)
        .first()
    )
    assert tenant_a_link.unlinked_at is not None
    assert tenant_b_link.unlinked_at is None


@patch("app.services.tenant_email_change.sync_email_across_gmail_accounts", return_value=NO_OP_GMAIL_SYNC_RESULT)
def test_no_change_when_email_unchanged(mock_sync, db_session):
    tenant = create_tenant(db_session, booking_id="B-change-nochange", email="same@example.com")
    conversation_id = make_conversation_matched_to_email(db_session, tenant.id, "same@example.com", "thread-nochange")

    handle_tenant_email_change(db_session, tenant, "same@example.com", "same@example.com")
    db_session.commit()

    assert db_session.query(Conversation).filter(Conversation.id == conversation_id).first() is not None
    mock_sync.assert_not_called()


@patch("app.services.tenant_email_change.sync_email_across_gmail_accounts", return_value=NO_OP_GMAIL_SYNC_RESULT)
def test_no_change_when_email_unchanged_case_insensitive(mock_sync, db_session):
    tenant = create_tenant(db_session, booking_id="B-change-case", email="Same@Example.com")

    handle_tenant_email_change(db_session, tenant, "Same@Example.com", "same@example.com")
    db_session.commit()

    mock_sync.assert_not_called()


@patch("app.services.tenant_email_change.sync_email_across_gmail_accounts", return_value=NO_OP_GMAIL_SYNC_RESULT)
def test_new_tenant_has_no_old_email_to_disconnect(mock_sync, db_session):
    tenant = create_tenant(db_session, booking_id="B-change-new", email=None)

    handle_tenant_email_change(db_session, tenant, None, "new@example.com")
    db_session.commit()

    mock_sync.assert_not_called()


@patch("app.services.tenant_email_change.sync_email_across_gmail_accounts", return_value=NO_OP_GMAIL_SYNC_RESULT)
def test_email_removed_still_disconnects_old_conversation_without_resync(mock_sync, db_session):
    tenant = create_tenant(db_session, booking_id="B-change-removed", email="old@example.com")
    conversation_id = make_conversation_matched_to_email(db_session, tenant.id, "old@example.com", "thread-removed")

    handle_tenant_email_change(db_session, tenant, "old@example.com", None)
    db_session.commit()

    assert db_session.query(Conversation).filter(Conversation.id == conversation_id).first() is None
    mock_sync.assert_not_called()
