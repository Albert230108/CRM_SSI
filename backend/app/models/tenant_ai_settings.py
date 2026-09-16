from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class TenantAiSettings(Base):
    __tablename__ = "tenant_ai_settings"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    default_email_template_id = Column(Integer, ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True)
    default_whatsapp_template_id = Column(Integer, ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True)
    auto_draft_email = Column(Boolean, nullable=False, default=False, server_default="false")
    auto_draft_whatsapp = Column(Boolean, nullable=False, default=False, server_default="false")
    auto_send_email = Column(Boolean, nullable=False, default=False, server_default="false")
    auto_send_whatsapp = Column(Boolean, nullable=False, default=False, server_default="false")
    # off      - today's behaviour: the operator picks the template, no planner/checker involved.
    # manual   - the "Run planner" button in the reply box runs the loop on demand.
    # auto     - the debounced inbound trigger runs the loop instead of the default-template path.
    # `auto` still obeys auto_draft_* / auto_send_*: the planner changes how a draft is produced,
    # never whether one is produced or sent.
    planner_mode = Column(String(10), nullable=False, default="off", server_default="off")
    # NULL falls back to the role's default profile, so changing the default reaches every
    # tenant that has not deliberately pinned a different one.
    planner_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    checker_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    drafter_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    # Independent of planner_mode: whether the debounced brain-writer step runs for this tenant.
    brain_writer_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    brain_writer_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    # Independent of planner_mode and brain_writer_enabled: whether the debounced action-writer
    # step runs for this tenant.
    # When on (default), a Beds24 booking webhook registers brain/action-writer triggers for this
    # tenant, so the brain/actions stay current with booking changes - not just inbound messages.
    # It only gates WHETHER those triggers are registered; the triggers still self-gate on
    # brain_writer_enabled / action_writer_enabled (both default off), so a default tenant sees no
    # AI activity from this until those are separately enabled.
    webhook_auto_run_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    action_writer_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    action_writer_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    # Independent of planner_mode and the raw draft/checker pipeline: whether the formatter stage
    # should turn an approved plain-text reply into channel-specific output.
    formatter_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    formatter_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    # The sales-manager profile this tenant uses when the planner asks for a quotation. NULL falls
    # back to the role's active default profile, like the other pins.
    sales_manager_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    # The executor profile this tenant uses to validate/apply a prepared Beds24 write. NULL falls
    # back to the role's active default profile, like the other pins.
    executor_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    # "manual" (validate on human approval, then push) or "autonomous" (validate and push without
    # a human). NULL means "inherit AdminSettings.executor_default_mode" - ships "manual", so no
    # tenant starts pushing to Beds24 unattended without an explicit opt-in.
    executor_mode = Column(String(12), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
