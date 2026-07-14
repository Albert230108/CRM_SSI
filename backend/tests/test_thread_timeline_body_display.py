from datetime import datetime, timezone

from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.services.thread_timeline_service import build_tenant_thread_timeline

QUOTED_BODY = (
    "Hi Brand,\n\nKind regards, Sander\n\n"
    "On Mon, 6 Jul 2026 at 20:25, brandscheffer <brandscheffer@protonmail.com>\n"
    "wrote:\n\n> Hi Sander\n>\n> Thank you.\n"
)


def test_grouped_thread_timeline_exposes_quote_stripped_body_display(db_session):
    """Regression: the merged timeline (the one ThreadView.tsx actually renders from,
    via GET /tenants/{id}/grouped-thread) used to drop body_text/body_html entirely
    because TimelineMessageRead didn't declare those fields, and never computed
    body_display at all, so quote-stripping silently never applied to it even though
    the sibling Gmail-only endpoint's schema had it.
    """
    tenant = Tenant(name="Tenant A", booking_id="B-timeline-1")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    conversation = Conversation(
        provider="gmail",
        provider_thread_id="thread-quote-1",
        tenant_id=tenant.id,
        subject="Re: House Search",
        last_message_at=datetime.now(timezone.utc),
    )
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)

    db_session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id="msg-quote-1",
            direction="outbound",
            sender_email="info@shortstayinn.com",
            recipient_email="brandscheffer@protonmail.com",
            subject="Re: House Search",
            body=QUOTED_BODY,
            sent_at=datetime.now(timezone.utc),
            raw_payload={"gmail": {"id": "msg-quote-1"}, "body_text": QUOTED_BODY, "body_html": None},
        )
    )
    db_session.commit()

    timeline = build_tenant_thread_timeline(db_session, tenant.id)
    thread_item = next(item for item in timeline.items if item.type == "email_thread")
    message = thread_item.messages[0]

    assert message.body_text == QUOTED_BODY
    assert message.body_display == "Hi Brand,\n\nKind regards, Sander"
