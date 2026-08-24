from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

STATUS_OPEN = "open"
STATUS_DONE = "done"
STATUS_DISMISSED = "dismissed"

SOURCE_MANUAL = "manual"
SOURCE_AI = "ai"


class ActionItem(Base):
    """A checklist item tied to a tenant - staff can add these manually, and the brain writer
    can propose them too (source="ai"), surfacing immediately like brain entries do, not gated
    behind approval (that gate is reserved for redo-driven memory/rule suggestions).
    """

    __tablename__ = "action_items"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    responsible_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default=STATUS_OPEN, server_default=STATUS_OPEN)
    source = Column(String(20), nullable=False)  # manual | ai
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
