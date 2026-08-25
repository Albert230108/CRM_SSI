from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, func

from app.database import Base


class AdminSettings(Base):
    __tablename__ = "admin_settings"

    id = Column(Integer, primary_key=True, index=True)
    forward_to_email = Column(String(255), nullable=True)
    # How long an inbound message's auto-draft debounce waits for the conversation to go quiet
    # before generating, and how long a generated auto-send draft waits before actually sending,
    # giving staff a window to intervene. Both editable in Admin Settings.
    ai_draft_debounce_seconds = Column(Integer, nullable=False, default=120, server_default="120")
    ai_auto_send_delay_seconds = Column(Integer, nullable=False, default=300, server_default="300")
    # How long the batched WhatsApp notification alert waits for a burst of new notifications
    # to go quiet before sending a single summarized message to opted-in staff, mirroring the
    # ai_draft_debounce_seconds pattern above.
    notification_whatsapp_debounce_seconds = Column(Integer, nullable=False, default=120, server_default="120")
    # Which WhatsApp account (external_account_id from WHATSAPP_SERVICE_ACCOUNTS /
    # WHATSAPP_SERVICE_URL_MAP) sends the batched notification alert. Deployments can run
    # multiple WhatsApp accounts/instances, so this must be picked explicitly rather than
    # assumed - NULL means unconfigured and alerts will fail until an admin sets one.
    notification_whatsapp_external_account_id = Column(String(255), nullable=True)
    # When true, every newly created tenant is automatically linked to all existing shared AI
    # reply templates (see tenants.py create_tenant), instead of starting with none available.
    ai_auto_apply_templates_to_new_tenants = Column(Boolean, nullable=False, default=False, server_default="false")
    # planner_mode given to newly created tenants (off | manual | auto). Existing tenants are
    # never retro-fitted, so turning this on cannot silently start drafting for live bookings.
    planner_default_mode = Column(String(10), nullable=False, default="off", server_default="off")
    # Brain/action writer defaults for newly created tenants only; existing tenants are never
    # retro-fitted, so toggling these cannot silently enable AI for live tenants.
    brain_writer_default_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    action_writer_default_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    # Ceiling on tokens the planner/checker loop may spend per calendar day (UTC) across all
    # tenants. NULL means unlimited. BigInteger because a busy day can exceed a 32-bit count.
    ai_daily_token_cap = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
