from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, Time, func

from app.database import Base


class BulkPlannerSchedule(Base):
    __tablename__ = "bulk_planner_schedules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    extra_instructions = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    run_time_local = Column(Time, nullable=False)
    status_filter = Column(JSON, nullable=True)
    last_message_within_days = Column(Integer, nullable=True)
    last_message_direction = Column(String(20), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
