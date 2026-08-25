from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    is_admin = Column(Boolean, nullable=False, default=False, server_default="false")
    whatsapp_notifications_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    default_gmail_account_id = Column(Integer, ForeignKey("gmail_accounts.id", ondelete="SET NULL"), nullable=True)
    default_whatsapp_account_id = Column(String(255), nullable=True)
    # A staff member on an @lid-addressed WhatsApp account replies from that @lid identity even
    # though we send to their plain phone number, so their phone alone cannot match an inbound
    # reply. Learned automatically when a notification is sent to them.
    whatsapp_identity_key = Column(String(255), nullable=True, index=True)
    tenant_status_filter = Column(JSON, nullable=True)
    pinned_tenant_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())