from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_DELETED = "deleted"


class TenantBrainEntryHistory(Base):
    """Audit log of every change to a tenant_brain_entries row, mirroring TenantNotesHistory.

    entry_id is nullable and SET NULL on delete so the history survives after the entry itself
    is removed, matching how a deleted entry's past states should still be inspectable.
    """

    __tablename__ = "tenant_brain_entry_history"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_id = Column(Integer, ForeignKey("tenant_brain_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(20), nullable=False)  # created | updated | deleted
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    source = Column(String(20), nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
