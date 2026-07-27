from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class TenantEmailAddress(Base):
    __tablename__ = "tenant_email_addresses"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    beds24_info_item_id = Column(String(100), nullable=True)
    beds24_sync_status = Column(String(20), nullable=False, server_default="pending")
    source = Column(String(50), nullable=False, server_default="manual")
    is_active = Column(Boolean, nullable=False, server_default="1")
    linked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    unlinked_at = Column(DateTime(timezone=True), nullable=True)
    unlinked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
