from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class ActionWriterTrigger(Base):
    """Debounce state for the action-writer agent: one row per (tenant, channel).

    Same shape and purpose as TenantBrainTrigger, but a separate queue so action-writing is
    independent of brain-writing, auto-draft debouncing, and planner_mode - it runs purely off
    its own per-tenant action_writer_enabled toggle.
    """

    __tablename__ = "action_writer_triggers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", name="uq_action_writer_triggers_tenant_channel"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    trigger_at = Column(DateTime(timezone=True), nullable=False, index=True)
    email_thread_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    whatsapp_endpoint_id = Column(Integer, ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
