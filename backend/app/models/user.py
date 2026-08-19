from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, func

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
    tenant_status_filter = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())