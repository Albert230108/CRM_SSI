from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, func, text

from app.database import Base


class TenantConversationLink(Base):
    __tablename__ = "tenant_conversation_links"
    __table_args__ = (
        # Uniqueness only applies to currently-active links so a tenant can be relinked
        # to the same conversation later without violating the constraint.
        Index(
            "uq_tenant_conversation_links_active",
            "tenant_id",
            "conversation_id",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
            sqlite_where=text("unlinked_at IS NULL"),
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    source = Column(String(50), nullable=False, server_default="email_match")
    matched_email = Column(String(255), nullable=True)
    is_visible = Column(Boolean, nullable=False, server_default=text("true"))
    unlinked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
