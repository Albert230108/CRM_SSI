from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.database import Base


class Communication(Base):
    __tablename__ = "communications"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    channel = Column(String(50), nullable=False)
    direction = Column(String(20), nullable=False, server_default="outbound")
    provider_message_id = Column(String(255), nullable=True, unique=True, index=True)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
