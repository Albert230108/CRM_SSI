from sqlalchemy import Column, DateTime, Integer, String, func

from app.database import Base


class AdminSettings(Base):
    __tablename__ = "admin_settings"

    id = Column(Integer, primary_key=True, index=True)
    forward_to_email = Column(String(255), nullable=True)
    # How long an inbound message's auto-draft debounce waits for the conversation to go quiet
    # before generating, and how long a generated auto-send draft waits before actually sending,
    # giving staff a window to intervene. Both editable in Admin Settings.
    ai_draft_debounce_seconds = Column(Integer, nullable=False, default=120, server_default="120")
    ai_auto_send_delay_seconds = Column(Integer, nullable=False, default=300, server_default="300")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
