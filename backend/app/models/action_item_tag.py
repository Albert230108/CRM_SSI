from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class ActionItemTag(Base):
    __tablename__ = "action_item_tags"
    __table_args__ = (UniqueConstraint("action_item_id", "tag_id", name="uq_action_item_tag"),)

    id = Column(Integer, primary_key=True, index=True)
    action_item_id = Column(Integer, ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id = Column(Integer, ForeignKey("action_tag_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")

    tag = relationship("ActionTagDefinition")
