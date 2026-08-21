from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class TenantBrainTrigger(Base):
    """Debounce state for the tenant-brain writer: one row per (tenant, channel).

    Same shape and purpose as AiAutoDraftTrigger, but a separate queue so brain-writing is
    independent of auto-draft debouncing and of planner_mode - it runs purely off its own
    per-tenant brain_writer_enabled toggle.
    """

    __tablename__ = "tenant_brain_triggers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", name="uq_tenant_brain_triggers_tenant_channel"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    trigger_at = Column(DateTime(timezone=True), nullable=False, index=True)
    email_thread_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    whatsapp_endpoint_id = Column(Integer, ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
