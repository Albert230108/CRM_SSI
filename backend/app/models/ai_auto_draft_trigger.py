from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class AiAutoDraftTrigger(Base):
    """Debounce state for auto-drafting: one row per (tenant, channel).

    Every qualifying inbound message resets trigger_at to now + debounce window instead of
    generating immediately, so a burst of messages collapses into a single generation once the
    conversation goes quiet. The background scheduler consumes (and deletes) rows once due.
    """

    __tablename__ = "ai_auto_draft_triggers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", name="uq_ai_auto_draft_triggers_tenant_channel"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    trigger_at = Column(DateTime(timezone=True), nullable=False, index=True)
    email_thread_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    whatsapp_endpoint_id = Column(Integer, ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
