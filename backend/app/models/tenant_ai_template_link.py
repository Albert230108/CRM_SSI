from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint, func

from app.database import Base


class TenantAiTemplateLink(Base):
    __tablename__ = "tenant_ai_template_links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_id", name="uq_tenant_ai_template_links_tenant_template"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("ai_reply_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
