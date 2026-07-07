from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func

from app.database import Base


class Communication(Base):
    __tablename__ = "communications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_message_id", name="uq_communications_tenant_provider_message_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    channel = Column(String(50), nullable=False)
    direction = Column(String(20), nullable=False, server_default="outbound")
    provider = Column(String(100), nullable=True, index=True)
    external_account_id = Column(String(255), nullable=True, index=True)
    external_phone_id = Column(String(255), nullable=True, index=True)
    external_chat_namespace = Column(String(255), nullable=True, index=True)
    whatsapp_chat_id = Column(String(255), nullable=True, index=True)
    provider_message_id = Column(String(255), nullable=True, index=True)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
