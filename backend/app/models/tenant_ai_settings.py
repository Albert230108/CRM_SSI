from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, func

from app.database import Base


class TenantAiSettings(Base):
    __tablename__ = "tenant_ai_settings"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    default_email_template_id = Column(Integer, ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True)
    default_whatsapp_template_id = Column(Integer, ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True)
    auto_draft_email = Column(Boolean, nullable=False, default=False, server_default="false")
    auto_draft_whatsapp = Column(Boolean, nullable=False, default=False, server_default="false")
    auto_send_email = Column(Boolean, nullable=False, default=False, server_default="false")
    auto_send_whatsapp = Column(Boolean, nullable=False, default=False, server_default="false")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
