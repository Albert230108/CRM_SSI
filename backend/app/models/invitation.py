from sqlalchemy import Column, DateTime, Integer, String, Boolean, func, ForeignKey

from app.database import Base


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False, server_default="false")
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
