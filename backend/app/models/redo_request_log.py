from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base


class RedoRequestLog(Base):
    """One row per redo attempt, from any entry point, regardless of whether regeneration
    succeeded - the accessible audit log of "what and why" staff have asked for on redos.

    Exactly one of ai_auto_draft_id / ai_agent_run_id is set, depending on which redo path
    produced this row: the WhatsApp/CRM approval-flow redo of a persisted AiAutoDraft, or the
    manual "Run planner" redo in the reply box (a one-off AiAgentRun, no AiAutoDraft involved).
    The new memory_redo_* fields track the dedicated rule-suggestion agent run and replay state.
    """

    __tablename__ = "redo_request_logs"

    id = Column(Integer, primary_key=True, index=True)
    ai_auto_draft_id = Column(Integer, ForeignKey("ai_auto_drafts.id", ondelete="CASCADE"), nullable=True, index=True)
    ai_agent_run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)  # whatsapp | crm
    what = Column(Text, nullable=False)
    why = Column(Text, nullable=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    memory_redo_run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
