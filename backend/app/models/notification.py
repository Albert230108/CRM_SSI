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
    # Points to the specific thread this notification is about, so clicking it can open that
    # thread directly instead of just landing on the tenant page. Interpretation depends on
    # channel: for "email" it's the Conversation.id; for "whatsapp" it's the Communication.id
    # of the inbound message (grouped-thread WhatsApp groups are recomputed on every load and
    # have no stable id of their own, so the frontend locates the group containing this message).
    thread_ref = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())
    # The message's actual send/receive time (Gmail internalDate, WhatsApp timestamp), as
    # opposed to created_at which is when this row was written. A delayed sync can insert a
    # notification for a message that arrived hours/days ago, so "how new is this" must be
    # judged from event_at, not created_at.
    event_at = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())
    # Set once this notification has been included in a sent batched WhatsApp alert, so the
    # flush job knows what's still pending. NULL means not yet dispatched.
    whatsapp_dispatched_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # Same idea for the batched push alert (independent from the WhatsApp batch): set once this
    # notification has been included in a dispatched push. NULL means not yet pushed.
    push_dispatched_at = Column(DateTime(timezone=True), nullable=True, index=True)


class NotificationReadState(Base):
    __tablename__ = "notification_reads"
    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", name="uq_notification_reads_notification_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
