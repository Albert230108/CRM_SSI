"""Resolve which concrete outbound target an AI reply should use for a chosen channel.

The planner may now instruct which channel (email/whatsapp) a reply should go out on
(see ai_agent_orchestrator.PLANNER_SCHEMA). When that choice differs from the channel the
conversation arrived on, we must find the concrete target for the *new* channel - an email
thread or a linked WhatsApp endpoint - before drafting, so an unreachable choice escalates
to a human instead of producing a draft that can never be sent.

This lives in its own module because both ai_agent_orchestrator (which decides/validates the
channel mid-run) and ai_auto_draft_service (which imports the orchestrator) need it; putting it
in either would create an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.gmail_integration import Conversation
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.tenant_conversation_link import TenantConversationLink

VALID_CHANNELS = ("email", "whatsapp")


@dataclass
class OutboundTarget:
    channel: str
    email_thread_id: int | None = None
    whatsapp_endpoint_id: int | None = None
    reachable: bool = True
    reason: str | None = None


def normalize_channel(value: object) -> str | None:
    """Coerce a planner-supplied channel value to 'email'/'whatsapp', or None if unusable."""
    if not isinstance(value, str):
        return None
    channel = value.strip().lower()
    return channel if channel in VALID_CHANNELS else None


def _latest_email_thread_id(db: Session, tenant_id: int) -> int | None:
    """The tenant's most-recently-active, still-visible email conversation, if any."""
    row = (
        db.query(Conversation.id)
        .join(
            TenantConversationLink,
            TenantConversationLink.conversation_id == Conversation.id,
        )
        .filter(
            TenantConversationLink.tenant_id == tenant_id,
            TenantConversationLink.unlinked_at.is_(None),
            TenantConversationLink.is_visible.is_(True),
        )
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
        .first()
    )
    return int(row[0]) if row else None


def resolve_outbound_target(
    db: Session,
    tenant: Tenant,
    channel: str,
    *,
    known_email_thread_id: int | None = None,
    known_whatsapp_endpoint_id: int | None = None,
) -> OutboundTarget:
    """Find the concrete send target for `channel`, preferring a target already known.

    `known_*` are the ids the inbound trigger already carried; when the chosen channel matches
    the inbound channel we simply reuse them. When the planner flipped the channel we look one
    up. An unreachable channel (no linked chat / no email thread / ambiguous WhatsApp) comes back
    with reachable=False and a human-readable reason so the caller can escalate.
    """
    if channel == "email":
        if known_email_thread_id is not None:
            return OutboundTarget("email", email_thread_id=known_email_thread_id)
        thread_id = _latest_email_thread_id(db, tenant.id)
        if thread_id is not None:
            return OutboundTarget("email", email_thread_id=thread_id)
        return OutboundTarget(
            "email", reachable=False, reason="No email thread is linked for this tenant"
        )

    if channel == "whatsapp":
        if known_whatsapp_endpoint_id is not None:
            return OutboundTarget("whatsapp", whatsapp_endpoint_id=known_whatsapp_endpoint_id)
        active_endpoints = (
            db.query(TenantChannelEndpoint)
            .filter(
                TenantChannelEndpoint.tenant_id == tenant.id,
                TenantChannelEndpoint.channel_type == "whatsapp",
                TenantChannelEndpoint.is_active.is_(True),
                TenantChannelEndpoint.unlinked_at.is_(None),
            )
            .all()
        )
        if len(active_endpoints) == 1:
            return OutboundTarget("whatsapp", whatsapp_endpoint_id=active_endpoints[0].id)
        if not active_endpoints:
            return OutboundTarget(
                "whatsapp", reachable=False, reason="No WhatsApp chat is linked for this tenant"
            )
        return OutboundTarget(
            "whatsapp",
            reachable=False,
            reason="This tenant has multiple WhatsApp chats linked; link a specific one",
        )

    return OutboundTarget(channel, reachable=False, reason=f"Unknown channel '{channel}'")
