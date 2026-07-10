from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, func, text

from app.database import Base


class TenantChannelEndpoint(Base):
    __tablename__ = "tenant_channel_endpoints"
    __table_args__ = (
        # Uniqueness only applies to currently-active endpoints so an unlinked (soft-deleted)
        # chat identity can be relinked later, either to the same thread or a different one.
        Index(
            "uq_tenant_channel_endpoints_route_active",
            "channel_type",
            "provider",
            "external_account_id",
            "external_chat_namespace",
            unique=True,
            postgresql_where=text("is_active = true AND unlinked_at IS NULL"),
            sqlite_where=text("is_active = 1 AND unlinked_at IS NULL"),
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    channel_type = Column(String(50), nullable=False, index=True)
    provider = Column(String(100), nullable=False, index=True)
    external_account_id = Column(String(255), nullable=True, index=True)
    external_phone_id = Column(String(255), nullable=True, index=True)
    external_chat_namespace = Column(String(255), nullable=True, index=True)
    webhook_token = Column(String(255), nullable=True, unique=True)
    signing_secret = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="1")
    chat_display_name = Column(String(255), nullable=True)
    source = Column(String(50), nullable=False, server_default="manual")
    linked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    unlinked_at = Column(DateTime(timezone=True), nullable=True)
    unlinked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


