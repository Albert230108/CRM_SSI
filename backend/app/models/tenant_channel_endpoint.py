from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class TenantChannelEndpoint(Base):
    __tablename__ = "tenant_channel_endpoints"
    __table_args__ = (UniqueConstraint("channel_type", "provider", "external_account_id", name="uq_tenant_channel_endpoints_route"),)

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    channel_type = Column(String(50), nullable=False, index=True)
    provider = Column(String(100), nullable=False, index=True)
    external_account_id = Column(String(255), nullable=False, index=True)
    external_phone_id = Column(String(255), nullable=True, index=True)
    external_chat_namespace = Column(String(255), nullable=True, index=True)
    webhook_token = Column(String(255), nullable=True, unique=True, index=True)
    signing_secret = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
