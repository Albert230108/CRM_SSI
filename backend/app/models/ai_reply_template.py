from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.database import Base


class AiReplyTemplate(Base):
    __tablename__ = "ai_reply_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    # Goal/explanation of this template's purpose, sent to Gemini as the first block of the prompt.
    guidelines = Column(Text, nullable=True)
    # Ordered list of {"label": str, "content": str} blocks, concatenated in array order to
    # form the background/system prompt sent to Gemini.
    sections = Column(JSON, nullable=False, default=list)
    include_history = Column(Boolean, nullable=False, default=False, server_default="false")
    history_message_limit = Column(Integer, nullable=True)
    include_beds24 = Column(Boolean, nullable=False, default=False, server_default="false")
    include_payments = Column(Boolean, nullable=False, default=False, server_default="false")
    include_notes = Column(Boolean, nullable=False, default=False, server_default="false")
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
