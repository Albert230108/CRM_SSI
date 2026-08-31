from sqlalchemy import Column, DateTime, Integer, func

from app.database import Base


class NotificationPushTrigger(Base):
    """Debounce state for the batched push notification: a single global row.

    Mirrors NotificationWhatsappTrigger. Every new Notification resets trigger_at to
    now + debounce window instead of pushing immediately, so a burst of notifications collapses
    into one push once things go quiet. The background scheduler consumes (and deletes) the row
    once due.
    """

    __tablename__ = "notification_push_triggers"

    id = Column(Integer, primary_key=True, index=True)
    trigger_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
