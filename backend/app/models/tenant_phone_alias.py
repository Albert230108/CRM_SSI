from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class TenantPhoneAlias(Base):
    __tablename__ = "tenant_phone_aliases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "normalized_phone", name="uq_tenant_phone_aliases_tenant_normalized_phone"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    normalized_phone = Column(String(64), nullable=False, index=True)
    raw_phone = Column(String(100), nullable=True)
    is_primary = Column(Boolean, nullable=False, server_default="0")
    source = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
