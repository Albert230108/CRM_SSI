from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

STATUS_ACTIVE = "active"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_DISMISSED = "dismissed"

SOURCE_MANUAL = "manual"
SOURCE_AI_SUGGESTED = "ai_suggested"


class WorkingMemoryRule(Base):
    """A global "if this then that" rule: plain condition/action text, not a structured
    condition builder - whenever rules are eventually wired into a drafting prompt, the model
    consumes them as semantic text, the same way it already reads template descriptions to pick
    a template. Not consumed by any prompt yet in this implementation; see tenant_brain_service
    and ai_agent_orchestrator for where that wiring would go.
    """

    __tablename__ = "working_memory_rules"

    id = Column(Integer, primary_key=True, index=True)
    condition_text = Column(Text, nullable=False)
    action_text = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default=STATUS_ACTIVE, server_default=STATUS_ACTIVE)
    source = Column(String(20), nullable=False, default=SOURCE_MANUAL, server_default=SOURCE_MANUAL)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
