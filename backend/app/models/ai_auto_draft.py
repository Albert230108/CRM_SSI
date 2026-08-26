from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base


class AiAutoDraft(Base):
    __tablename__ = "ai_auto_drafts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True)
    email_thread_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    whatsapp_endpoint_id = Column(Integer, ForeignKey("tenant_channel_endpoints.id", ondelete="SET NULL"), nullable=True)
    generated_text = Column(Text, nullable=False)
    # The formatter's output, if any. Stored separately so generated_text stays the raw draft
    # used for audit, checker verification and regeneration.
    formatted_text = Column(Text, nullable=True)
    # The inbound message this draft answers, framed for human display only (e.g. "Replying to:
    # ..."). Never concatenated into generated_text - that column is exactly what gets sent to
    # the tenant, so the quoted context must live separately or it leaks into the outbound message.
    quoted_context = Column(Text, nullable=True)
    # pending -> pending_auto_send -> sent, or pending -> dismissed / used_as_manual_seed.
    # A draft superseded by a fresher one (new inbound message before it was acted on) moves to
    # "superseded" rather than being deleted, so the automatic pipeline keeps a full audit trail.
    # "needs_review" is a terminal state for planner drafts the checker never approved: they are
    # shown to staff but are deliberately excluded from the auto-send scheduler.
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    scheduled_send_at = Column(DateTime(timezone=True), nullable=True)
    sent_communication_id = Column(Integer, ForeignKey("communications.id", ondelete="SET NULL"), nullable=True)
    # Set when the draft came out of the planner loop, linking it to its full execution log.
    agent_run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True)
    checker_feedback = Column(Text, nullable=True)
    # Why this draft ended up sent or dismissed, and who/what decided - set at every path that
    # reaches a final send/dismiss outcome (CRM UI buttons, a WhatsApp YES/NO reply, or the
    # automatic auto-send timer). Read by memory_redo_service as extra context for the redo
    # agent - see ai_draft_approval_service.py, api/ai_auto_drafts.py, ai_auto_draft_service.py.
    resolution_reason = Column(Text, nullable=True)
    resolution_source = Column(String(20), nullable=True)  # human_ui | human_whatsapp | auto_timer
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
