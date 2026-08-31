from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, Time, func
from sqlalchemy.orm import relationship

from app.database import Base

STATUS_OPEN = "open"
STATUS_DONE = "done"
STATUS_DISMISSED = "dismissed"

SOURCE_MANUAL = "manual"
SOURCE_AI = "ai"


class ActionItem(Base):
    """A checklist item tied to a tenant, or a general tenant-less item.

    Staff can add these manually, and the action writer can propose new ones too
    (source="ai"), surfacing immediately like brain entries do. AI proposals to modify or
    delete an *existing* item go through MemorySuggestion approval instead - see
    action_writer_service.py and memory_suggestion_service.py.
    """

    __tablename__ = "action_items"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # Separate from description: a directive for the planner when this action triggers an AI run.
    # Manually editable, or filled by the action-writer agent - see action_writer_service.py.
    ai_instruction = Column(Text, nullable=True)
    responsible_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(Date, nullable=True)
    # Time-of-day for the due date. Together with due_date it defines when a "triggers planner"
    # action fires the planner (see action_planner_trigger_service.py). Missing time defaults to
    # 09:00 Europe/Amsterdam there.
    due_time = Column(Time, nullable=True)
    status = Column(String(20), nullable=False, default=STATUS_OPEN, server_default=STATUS_OPEN)
    source = Column(String(20), nullable=False)  # manual | ai
    priority = Column(String(4), nullable=True)  # p1 (highest) .. p4, or NULL for none
    # NULL means not recurring. When set, completing this item creates the next occurrence -
    # see action_item_service.complete.
    recurrence_interval_days = Column(Integer, nullable=True)
    # "due_date" (fixed cadence, counts from the original due date) or "completed_at" (floating
    # cadence, counts from whenever it was actually completed). Only meaningful when
    # recurrence_interval_days is set.
    recurrence_anchor = Column(String(20), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Set when a per-action planner run has fired for the current due date/time, so the scheduler
    # sweep does not re-fire every tick. Cleared when due_date/due_time change (fire once per due
    # change) - see action_item_service.update.
    planner_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    tag_links = relationship(
        "ActionItemTag",
        cascade="all, delete-orphan",
        order_by="ActionItemTag.position, ActionItemTag.id",
    )

    @property
    def tag_ids(self) -> list[int]:
        return [link.tag_id for link in self.tag_links]
