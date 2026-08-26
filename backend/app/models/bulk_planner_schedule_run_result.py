from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base


class BulkPlannerScheduleRunResult(Base):
    __tablename__ = "bulk_planner_schedule_run_results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("bulk_planner_schedule_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)
    outcome = Column(String(20), nullable=False)
    skip_reason = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    draft_id = Column(Integer, ForeignKey("ai_auto_drafts.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
