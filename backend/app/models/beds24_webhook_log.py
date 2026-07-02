from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, func

from app.database import Base


class Beds24WebhookLog(Base):
    __tablename__ = "beds24_webhook_logs"

    id = Column(Integer, primary_key=True, index=True)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    event_type = Column(String(100), nullable=True, index=True)
    status = Column(String(50), nullable=False, index=True)
    booking_id = Column(String(100), nullable=True, index=True)
    room_id = Column(String(100), nullable=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    http_status = Column(Integer, nullable=True)
    result_message = Column(String(500), nullable=True)
    error_summary = Column(String(500), nullable=True)
    error_traceback = Column(Text, nullable=True)
    raw_payload = Column(JSON, nullable=False)
    parsed_fields = Column(JSON, nullable=True)
