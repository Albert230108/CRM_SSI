from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class AssistantMessage(Base):
    """One turn of a saved CRM-copilot chat (see assistant_conversation.py).

    `tool_trace` records which tools an assistant turn requested and what they returned, purely
    for transparency in the widget/history view - it is not replayed into later prompts, which
    instead only see the rendered `content`.
    """

    __tablename__ = "assistant_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    tool_trace = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    conversation = relationship("AssistantConversation", back_populates="messages")
