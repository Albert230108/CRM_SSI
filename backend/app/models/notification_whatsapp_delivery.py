from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class NotificationWhatsappDelivery(Base):
    """Audit log of each attempt to send a batched WhatsApp notification alert to a user."""

    __tablename__ = "notification_whatsapp_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    phone = Column(String(100), nullable=False)
    notification_count = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    error_message = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
