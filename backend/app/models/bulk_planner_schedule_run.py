from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class BulkPlannerScheduleRun(Base):
    __tablename__ = "bulk_planner_schedule_runs"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("bulk_planner_schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    trigger_reason = Column(String(20), nullable=False, default="scheduled", server_default="scheduled")
    matched_tenant_count = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String(20), nullable=False, default="running", server_default="running")
