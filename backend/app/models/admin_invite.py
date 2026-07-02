from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class AdminInvite(Base):
    __tablename__ = "admin_invites"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=True, index=True)
    full_name = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    role = Column(String(20), nullable=False, default="non-admin", server_default="non-admin")
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())