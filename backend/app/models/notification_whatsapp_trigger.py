from sqlalchemy import Column, DateTime, Integer, func

from app.database import Base


class NotificationWhatsappTrigger(Base):
    """Debounce state for the batched WhatsApp notification alert: a single global row.

    Every new Notification resets trigger_at to now + debounce window instead of alerting
    immediately, so a burst of notifications collapses into one WhatsApp message once things
    go quiet. The background scheduler consumes (and deletes) the row once due.
    """

    __tablename__ = "notification_whatsapp_triggers"

    id = Column(Integer, primary_key=True, index=True)
    trigger_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
