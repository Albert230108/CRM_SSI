from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base

# Terminal run statuses.
STATUS_COMPLETED = "completed"       # checker passed; the draft is usable
STATUS_NEEDS_REVIEW = "needs_review"  # redraft attempts exhausted; a human must look
STATUS_ESCALATED = "escalated"        # deliberately not drafted (guardrail, low confidence, cap)
STATUS_SKIPPED = "skipped"            # planner decided no reply is warranted
STATUS_FAILED = "failed"              # the model or the pipeline errored


class AiAgentRun(Base):
    """One end-to-end planner -> drafter -> checker execution, kept for inspection.

    Every model call made during the run is recorded as a step, so an operator can see exactly
    which template was chosen and why, what the checker objected to, and what it all cost.
    """

    __tablename__ = "ai_agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False, index=True)
    mode = Column(String(20), nullable=False)  # manual | auto
    status = Column(String(20), nullable=False, index=True)
    escalation_reason = Column(String(60), nullable=True)
    planner_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    checker_profile_id = Column(Integer, ForeignKey("ai_agent_profiles.id", ondelete="SET NULL"), nullable=True)
    final_template_id = Column(Integer, ForeignKey("ai_reply_templates.id", ondelete="SET NULL"), nullable=True)
    final_text = Column(Text, nullable=True)
    checker_feedback = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    total_prompt_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    total_output_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    duration_ms = Column(Integer, nullable=False, default=0, server_default="0")
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    steps = relationship(
        "AiAgentRunStep",
        cascade="all, delete-orphan",
        order_by="AiAgentRunStep.step_index, AiAgentRunStep.id",
        back_populates="run",
    )


class AiAgentRunStep(Base):
    """A single model call within a run.

    `stage` is intentionally open-ended rather than an enum: a later phase adds an "action"
    stage for planner-triggered API side-effects, which should not require a schema change.
    """

    __tablename__ = "ai_agent_run_steps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("ai_agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_index = Column(Integer, nullable=False, default=0, server_default="0")
    stage = Column(String(20), nullable=False)  # planner | drafter | checker
    model = Column(String(120), nullable=True)
    prompt = Column(Text, nullable=True)
    response = Column(Text, nullable=True)
    # The validated JSON for planner/checker stages - this is where the planner's `reasoning`
    # and the alternatives it rejected are kept.
    parsed = Column(JSON, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run = relationship("AiAgentRun", back_populates="steps")
