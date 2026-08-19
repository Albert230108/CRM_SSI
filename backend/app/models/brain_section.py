from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class BrainSection(Base):
    """A node in the single global knowledge tree ("the Brain").

    Templates reference nodes instead of duplicating their text, so a policy change is made
    once here and every template that points at it is updated at the same time.
    """

    __tablename__ = "brain_sections"
    __table_args__ = (UniqueConstraint("parent_id", "slug", name="uq_brain_sections_parent_slug"),)

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("brain_sections.id", ondelete="CASCADE"), nullable=True, index=True)
    # Dotted path built from the slug chain (e.g. "policies.cancellation"). Denormalised so
    # {{brain:...}} token resolution is a single indexed lookup instead of a recursive walk;
    # recomputed for the whole subtree whenever a node is renamed or reparented.
    path = Column(String(600), nullable=False, unique=True, index=True)
    slug = Column(String(120), nullable=False)
    title = Column(String(255), nullable=False)
    # A node may be a pure container with no text of its own.
    content = Column(Text, nullable=True)
    # Hex string (e.g. "#3b82f6") used to color-code the section in the tree UI. Null means
    # "no color assigned" rather than any particular default.
    color = Column(String(7), nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    parent = relationship("BrainSection", remote_side=[id], back_populates="children")
    children = relationship(
        "BrainSection",
        cascade="all, delete-orphan",
        back_populates="parent",
        order_by="BrainSection.position, BrainSection.id",
    )
