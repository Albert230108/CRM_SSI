from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from app.database import Base


class CommunicationAttachment(Base):
    """A stored file blob, tenant-scoped and message-agnostic.

    This is the blob registry only - it does not say which message(s) an attachment
    appears on. That's CommunicationAttachmentLink, so the same blob can be linked to
    both sides of a dual-write (a Gmail send creates a Communication row and a
    ConversationMessage row for the same send) and reused across separate re-attach-
    from-history sends without duplicating bytes on disk.
    """

    __tablename__ = "communication_attachments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sha256", name="uq_communication_attachments_tenant_sha256"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_key = Column(String(512), nullable=False, unique=True)
    filename = Column(Text, nullable=False)
    mime_type = Column(String(255), nullable=True)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    origin = Column(String(20), nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CommunicationAttachmentLink(Base):
    """Which message an attachment appears on.

    communication_id and conversation_message_id are both nullable because a single
    Gmail send writes two rows for the same attachment_id (one per side of the dual
    write in email_outbound_persistence.py), and a WhatsApp send or inbound webhook
    only ever populates communication_id.
    """

    __tablename__ = "communication_attachment_links"
    __table_args__ = (
        CheckConstraint(
            "communication_id IS NOT NULL OR conversation_message_id IS NOT NULL",
            name="ck_communication_attachment_links_target",
        ),
    )

    id = Column(Integer, primary_key=True)
    attachment_id = Column(
        Integer, ForeignKey("communication_attachments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    communication_id = Column(Integer, ForeignKey("communications.id", ondelete="CASCADE"), nullable=True, index=True)
    conversation_message_id = Column(
        Integer, ForeignKey("conversation_messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    position = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
