from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base


class AiAutoDraft(Base):
    __tablename__ = "ai_auto_drafts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True)
    email_thread_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    whatsapp_endpoint_id = Column(Integer, ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True)
    generated_text = Column(Text, nullable=False)
    # pending -> pending_auto_send -> sent, or pending -> dismissed / used_as_manual_seed.
    # A draft superseded by a fresher one (new inbound message before it was acted on) moves to
    # "superseded" rather than being deleted, so the automatic pipeline keeps a full audit trail.
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    scheduled_send_at = Column(DateTime(timezone=True), nullable=True)
    sent_communication_id = Column(Integer, ForeignKey("communications.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
