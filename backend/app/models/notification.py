from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_name = Column(String(255), nullable=True)
    channel = Column(String(50), nullable=False)
    direction = Column(String(20), nullable=False, server_default="inbound")
    preview = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())
    # The message's actual send/receive time (Gmail internalDate, WhatsApp timestamp), as
    # opposed to created_at which is when this row was written. A delayed sync can insert a
    # notification for a message that arrived hours/days ago, so "how new is this" must be
    # judged from event_at, not created_at.
    event_at = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())


class NotificationReadState(Base):
    __tablename__ = "notification_reads"
    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_notification_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
