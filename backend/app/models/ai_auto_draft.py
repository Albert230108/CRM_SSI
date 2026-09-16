from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.database import Base

# A planner draft whose background generation is still in flight (generated_text is empty). The
# UI keys a spinner off this so it never renders an empty draft as if it were finished.
STATUS_GENERATING = "generating"


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
    # generating -> pending / needs_review, then pending -> pending_auto_send -> sent, or
    # pending -> dismissed / used_as_manual_seed. "generating" marks a draft whose planner loop is
    # still running in the background: its generated_text is still empty, so the UI shows a
    # spinner instead of an empty draft. Every planner completion path overwrites it with a
    # terminal status. A draft superseded by a fresher one (new inbound message before it was
    # acted on) moves to "superseded" rather than being deleted, so the automatic pipeline keeps a
    # full audit trail. "needs_review" is a terminal state for planner drafts the checker never
    # approved: they are shown to staff but are deliberately excluded from the auto-send scheduler.
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    scheduled_send_at = Column(DateTime(timezone=True), nullable=True)
    sent_communication_id = Column(Integer, ForeignKey("communications.id", ondelete="SET NULL"), nullable=True)
    # Set when the draft came out of the planner loop, linking it to its full execution log.
    agent_run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True)
    checker_feedback = Column(Text, nullable=True)
    # Legacy: set when the sales-manager agent stored a quotation PDF as a CommunicationAttachment
    # (before the path-based attachment flow). Still read as a fallback for old drafts - see
    # ai_auto_draft_service._draft_quotation_attachments. New drafts use quotation_file_path below.
    quotation_attachment_id = Column(
        Integer, ForeignKey("communication_attachments.id", ondelete="SET NULL"), nullable=True
    )
    # The quotation PDF path the sales manager generated for this reply, relative to
    # TENANT_FILES_ROOT (the mount shared with the quotation-manager service). Bytes are read
    # lazily at send time (tenant_files_storage.resolve_download_path) rather than stored here, so
    # a delayed auto-send still attaches it without carrying the PDF through the draft row.
    quotation_file_path = Column(Text, nullable=True)
    quotation_filename = Column(String(255), nullable=True)
    # Set when the sales manager prepared a Beds24 write for this reply (an invoice-item update or
    # a brand-new booking - sales_manager_service.build_pending_execution's shape). It is never
    # pushed to Beds24 until the executor agent validates it, which happens either on human
    # approval of this draft or autonomously, depending on the tenant's executor_mode setting (see
    # ai_auto_draft_service._execute_pending / send_scheduled_draft). Cleared on success. A draft
    # carrying this is kept out of "pending_auto_send" in manual mode (_planner_draft_status_and_
    # schedule); autonomous mode allows it there, subject to the usual auto-send checks.
    pending_execution = Column(JSON, nullable=True)
    # The executor's own AiAgentRun, once it has judged (or applied) pending_execution - lets the
    # approval UI show why it was approved/blocked.
    executor_run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="SET NULL"), nullable=True)
    # Why this draft ended up sent or dismissed, and who/what decided - set at every path that
    # reaches a final send/dismiss outcome (CRM UI buttons, a WhatsApp YES/NO reply, or the
    # automatic auto-send timer). Read by memory_redo_service as extra context for the redo
    # agent - see ai_draft_approval_service.py, api/ai_auto_drafts.py, ai_auto_draft_service.py.
    resolution_reason = Column(Text, nullable=True)
    resolution_source = Column(String(20), nullable=True)  # human_ui | human_whatsapp | auto_timer
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
