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
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
