from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class RunQaMessage(Base):
    """One turn of the persisted chat for asking questions about a specific AI agent run.

    Unlike the redo QA chat (which is keyed on a redo log), this chat is keyed directly on the
    `AiAgentRun` being debugged, so it works for planner, brain-writer, and action-writer runs
    alike - they are all `AiAgentRun` rows.
    """

    __tablename__ = "run_qa_messages"

    id = Column(Integer, primary_key=True, index=True)
    # The run being debugged - the subject of the conversation.
    agent_run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    # The QA run this assistant turn generated (token accounting), mirroring redo QA's link. Null
    # for user turns and when the run was cleaned up.
    qa_run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    asked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
