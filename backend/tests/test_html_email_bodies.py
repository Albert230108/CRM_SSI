"""Regression tests for HTML-only email bodies reaching the AI prompts.

_extract_text() only ever decoded text/plain parts, so a message sent as text/html alone
persisted with body="". Everything downstream then degraded silently: the conversation
history rendered as "Subject: " with nothing after it, and latest_inbound_text() returned
"" - which is falsy, so the "Message To Answer" block was dropped from the planner and
checker prompts entirely. The model answered from the subject line alone.
"""

import base64

import app.api.gmail_integration as gmail_integration
from app.models.gmail_integration import ConversationMessage, GmailAccount
from app.models.tenant import Tenant
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.tenant_email_address import TenantEmailAddress
from app.services import ai_agent_orchestrator, ai_reply_service
from app.services.html_text import html_to_text


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def test_html_to_text_renders_block_structure():
    html = "<html><head><style>p{color:red}</style></head><body><p>Hi Alex,</p><p>Can I check in early?</p></body></html>"
    assert html_to_text(html) == "Hi Alex,\n\nCan I check in early?"


def test_html_to_text_decodes_entities_and_drops_scripts():
    assert html_to_text("<p>caf&eacute; &amp; bar</p><script>alert('x')</script>") == "café & bar"


def test_html_to_text_handles_empty_and_malformed_input():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""
    assert html_to_text("   ") == ""
    assert html_to_text("<style>body{}</style>") == ""
    assert html_to_text("<p>unclosed") == "unclosed"


def test_html_only_message_persists_a_readable_body(db_session):
    """The stored body must be non-empty for a message that carries no text/plain part."""
    account = GmailAccount(email_address="html-account@example.com", is_active=True)
    tenant = Tenant(name="HTML Tenant", booking_id="B-html-1")
    db_session.add_all([account, tenant])
    db_session.commit()
    db_session.add(TenantEmailAddress(tenant_id=tenant.id, email="guest-html@example.com", is_active=True))
    db_session.commit()

    thread = {
        "id": "thread-html-only",
        "messages": [
            {
                "id": "msg-html-only",
                "internalDate": "1700000000000",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/html",
                    "headers": [
                        {"name": "From", "value": "guest-html@example.com"},
                        {"name": "To", "value": "html-account@example.com"},
                        {"name": "Subject", "value": "Early check-in"},
                    ],
                    "body": {"data": _encode("<html><body><p>Can I check in at 2pm?</p></body></html>")},
                },
            }
        ],
    }

    conversation = gmail_integration._upsert_thread(db_session, account, thread)
    db_session.commit()
    assert conversation is not None

    message = (
        db_session.query(ConversationMessage)
        .filter(ConversationMessage.provider_message_id == "msg-html-only")
        .one()
    )
    assert message.body.strip() == "Can I check in at 2pm?"
    # The preview shown in the thread list came from the same extraction.
    assert conversation.preview_text and "2pm" in conversation.preview_text


def test_latest_inbound_text_reads_an_html_only_message_from_the_db(db_session):
    """Drives latest_inbound_text through the DB rather than passing inbound_text= directly.

    The existing planner/checker prompt tests hand inbound_text in explicitly, so they never
    exercised the query that actually loads ConversationMessage.body - which is where this
    failed in production.
    """
    account = GmailAccount(email_address="html-account-2@example.com", is_active=True)
    tenant = Tenant(name="HTML Tenant 2", booking_id="B-html-2")
    db_session.add_all([account, tenant])
    db_session.commit()
    db_session.add(TenantEmailAddress(tenant_id=tenant.id, email="guest-html2@example.com", is_active=True))
    db_session.commit()

    thread = {
        "id": "thread-html-only-2",
        "messages": [
            {
                "id": "msg-html-only-2",
                "internalDate": "1700000000000",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/html",
                    "headers": [
                        {"name": "From", "value": "guest-html2@example.com"},
                        {"name": "To", "value": "html-account-2@example.com"},
                        {"name": "Subject", "value": "Parking"},
                    ],
                    "body": {"data": _encode("<div>Is there parking at the property?</div>")},
                },
            }
        ],
    }
    conversation = gmail_integration._upsert_thread(db_session, account, thread)
    db_session.commit()
    assert conversation is not None
    assert (
        db_session.query(TenantConversationLink)
        .filter(TenantConversationLink.tenant_id == tenant.id)
        .count()
        == 1
    )

    inbound = ai_agent_orchestrator.latest_inbound_text(db_session, tenant.id, "email")
    assert inbound == "Is there parking at the property?"

    # And it reaches the history block rather than rendering as a bare subject.
    history = ai_reply_service._build_history_context(db_session, tenant, 10, channels="email")
    assert "Is there parking at the property?" in history
    assert "Parking: \n" not in history
