from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, func, text

from app.database import Base


class CommunicationReplyDraft(Base):
    """An unsent reply body parked against one specific conversation scope.

    Scope is either a single email thread or a single manually-linked WhatsApp chat, never
    the tenant as a whole: a draft written for one thread must never surface in another
    thread's reply box, nor in another tenant's.

    WhatsApp drafts key on the TenantChannelEndpoint (the manual chat link) rather than on
    the timeline's group_id/block_id, because those are derived from message timestamps and
    counts in thread_timeline_service and therefore change whenever a new message arrives.
    """

    __tablename__ = "communication_reply_drafts"
    __table_args__ = (
        CheckConstraint(
            "(channel = 'email' AND email_thread_id IS NOT NULL AND whatsapp_endpoint_id IS NULL)"
            " OR (channel = 'whatsapp' AND whatsapp_endpoint_id IS NOT NULL AND email_thread_id IS NULL)",
            name="ck_communication_reply_drafts_scope",
        ),
        # One draft per scope. Partial indexes because only one of the two scope columns is
        # populated per row, and NULLs would otherwise defeat a plain composite unique index.
        Index(
            "uq_communication_reply_drafts_email",
            "tenant_id",
            "email_thread_id",
            unique=True,
            postgresql_where=text("channel = 'email'"),
            sqlite_where=text("channel = 'email'"),
        ),
        Index(
            "uq_communication_reply_drafts_whatsapp",
            "tenant_id",
            "whatsapp_endpoint_id",
            unique=True,
            postgresql_where=text("channel = 'whatsapp'"),
            sqlite_where=text("channel = 'whatsapp'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    email_thread_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True)
    whatsapp_endpoint_id = Column(
        Integer, ForeignKey("tenant_channel_endpoints.id", ondelete="CASCADE"), nullable=True, index=True
    )
    subject = Column(Text, nullable=True)
    body = Column(Text, nullable=True)
    # Audit only - drafts are shared across users, so this is deliberately not part of the key.
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
