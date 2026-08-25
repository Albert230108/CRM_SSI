from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.database import Base


class ActionTagDefinition(Base):
    """One entry in the global, admin-configurable action-tag palette.

    Same admin-authored, position-ordered, is_active-flagged shape as BrainFieldDefinition.
    `color` is a hex string used as the tag pill's fill background in the UI. ActionItem.tag_ids
    is a multi-select relationship into this table - staff can choose several tags, and the
    action-writer agent may only choose from the currently active names (see
    action_writer_service.py).
    """

    __tablename__ = "action_tag_definitions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), nullable=False, unique=True, index=True)
    color = Column(String(20), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
