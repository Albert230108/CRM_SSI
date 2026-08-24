from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func

from app.database import Base

PLANNER_ROLE = "planner"
CHECKER_ROLE = "checker"
# The drafter writes the reply itself. Its profile carries prompt text only - the model,
# sampling and context budget for a draft still come from the reply template.
DRAFTER_ROLE = "drafter"
# Decides, independently of the planner, whether the latest message is worth remembering
# long-term for this tenant. Runs on its own debounced trigger - see tenant_brain_service.py.
BRAIN_WRITER_ROLE = "brain_writer"
# Reads a redo's "what"/"why" feedback and proposes working-memory/rule changes for a human to
# approve - see memory_redo_service.py. Never applies anything itself.
MEMORY_REDO_ROLE = "memory_redo"
# Answers a staff member's ad-hoc question about one tenant's working memory - see
# memory_qa_service.py. Read-only; never writes to the brain/fields/action list.
MEMORY_QA_ROLE = "memory_qa"


class AiAgentProfile(Base):
    """A named, reusable configuration for one of the two AI agents in the reply loop.

    Both roles share a table because they share most of their settings (instructions, model,
    sampling, how much context to load); the handful of role-specific knobs are nullable and
    only meaningful for their own role.
    """

    __tablename__ = "ai_agent_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, index=True)  # planner | checker | drafter | brain_writer | memory_redo | memory_qa
    # Exactly one profile per role is the fallback used by tenants that have not pinned one.
    is_default = Column(Boolean, nullable=False, default=False, server_default="false")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # The operator-written rules that define this agent's job. Sent as the first prompt block.
    instructions = Column(Text, nullable=True)
    # Overrides for the fixed prompt scaffolding defined in services/ai_prompt_blocks.py,
    # keyed by block key. A key present here wins even when its value is an empty string -
    # that is how an operator removes a block. A key absent falls back to the built-in text.
    prompt_blocks = Column(JSON, nullable=False, default=dict, server_default="{}")

    # --- Model & sampling -------------------------------------------------------------
    # NULL means "use the process-wide GEMINI_MODEL", so profiles do not silently pin an old
    # model when the deployment's default is upgraded.
    model = Column(String(120), nullable=True)
    temperature = Column(Float, nullable=True)
    max_output_tokens = Column(Integer, nullable=True)

    # --- Context budget ---------------------------------------------------------------
    history_limit = Column(Integer, nullable=False, default=40, server_default="40")
    # both | inbound | email | whatsapp - "inbound" follows the channel the message arrived on.
    history_channels = Column(String(20), nullable=False, default="both", server_default="both")
    history_lookback_days = Column(Integer, nullable=True)
    include_beds24 = Column(Boolean, nullable=False, default=True, server_default="true")
    include_payments = Column(Boolean, nullable=False, default=False, server_default="false")
    include_notes = Column(Boolean, nullable=False, default=True, server_default="true")
    include_availability = Column(Boolean, nullable=False, default=False, server_default="false")
    # Planner only: whether to show the brain's table of contents so it can request sections.
    include_brain_index = Column(Boolean, nullable=False, default=True, server_default="true")

    # --- Guardrails & escalation ------------------------------------------------------
    match_inbound_language = Column(Boolean, nullable=False, default=True, server_default="true")
    # Case-insensitive substrings that park the conversation for a human instead of drafting.
    escalate_keywords = Column(JSON, nullable=False, default=list)
    # Planner only: what to do when no template fits or confidence is too low.
    on_no_template_match = Column(String(20), nullable=False, default="escalate", server_default="escalate")
    min_confidence = Column(Float, nullable=False, default=0.5, server_default="0.5")

    # --- Checker only -----------------------------------------------------------------
    max_redraft_attempts = Column(Integer, nullable=False, default=2, server_default="2")
    block_auto_send_on_fail = Column(Boolean, nullable=False, default=True, server_default="true")

    # --- Cost -------------------------------------------------------------------------
    # NULL means unlimited; counted across this profile's own calls only.
    daily_token_cap = Column(Integer, nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
