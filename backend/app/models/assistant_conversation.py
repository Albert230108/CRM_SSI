from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class AssistantConversation(Base):
    """One saved chat with the floating CRM copilot, scoped to the user who started it.

    A user can keep several of these open at once (see the widget's conversation switcher) -
    unlike memory_qa/run_qa, which are always scoped to one tenant/run and have exactly one
    thread each, the copilot roams the whole app, so its chats need an explicit grouping and a
    title of their own.
    """

    __tablename__ = "assistant_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False, default="New chat", server_default="New chat")
    # One AiAgentRun logs this whole chat: later questions append steps to it instead of creating
    # a fresh run each turn. SET NULL so deleting the run never removes the conversation.
    agent_run_id = Column(
        Integer, ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    messages = relationship(
        "AssistantMessage",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.created_at, AssistantMessage.id",
        back_populates="conversation",
    )
