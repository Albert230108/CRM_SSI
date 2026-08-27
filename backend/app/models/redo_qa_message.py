from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class RedoQaMessage(Base):
    """One turn of the persisted chat for asking questions about a specific redo request."""

    __tablename__ = "redo_qa_messages"

    id = Column(Integer, primary_key=True, index=True)
    redo_request_log_id = Column(Integer, ForeignKey("redo_request_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    ai_agent_run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    asked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
