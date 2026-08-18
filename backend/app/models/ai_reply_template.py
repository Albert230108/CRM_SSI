from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class AiReplyTemplateBrainSection(Base):
    """Explicit brain sections attached to a template, rendered as the Knowledge Base block."""

    __tablename__ = "ai_reply_template_brain_sections"
    __table_args__ = (
        UniqueConstraint("template_id", "brain_section_id", name="uq_ai_template_brain_section"),
    )

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(
        Integer, ForeignKey("ai_reply_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brain_section_id = Column(
        Integer, ForeignKey("brain_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position = Column(Integer, nullable=False, default=0, server_default="0")

    brain_section = relationship("BrainSection")


class AiReplyTemplate(Base):
    __tablename__ = "ai_reply_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    # What this template is for, in the operator's own words. Read by the Planner when it
    # chooses a template; never sent to the drafting model (that is what `guidelines` is for).
    description = Column(Text, nullable=True)
    # Goal/explanation of this template's purpose, sent to Gemini as the first block of the prompt.
    guidelines = Column(Text, nullable=True)
    # Ordered list of {"label": str, "content": str, "id": str, "x": float, "y": float,
    # "order": int} blocks. Concatenated in array order (kept in sync with "order" by the
    # client) to form the background/system prompt sent to Gemini; "id"/"x"/"y" are canvas-only
    # metadata, ignored by the prompt builder.
    sections = Column(JSON, nullable=False, default=list)
    # Freeform organizational post-it notes on the section canvas: list of {id, text, x, y,
    # color}. Never read by the prompt builder - explicitly excluded from what is sent to Gemini.
    canvas_notes = Column(JSON, nullable=False, default=list, server_default="[]")
    include_history = Column(Boolean, nullable=False, default=False, server_default="false")
    history_message_limit = Column(Integer, nullable=True)
    include_beds24 = Column(Boolean, nullable=False, default=False, server_default="false")
    include_payments = Column(Boolean, nullable=False, default=False, server_default="false")
    include_notes = Column(Boolean, nullable=False, default=False, server_default="false")
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    brain_links = relationship(
        AiReplyTemplateBrainSection,
        cascade="all, delete-orphan",
        order_by="AiReplyTemplateBrainSection.position, AiReplyTemplateBrainSection.id",
    )

    @property
    def brain_section_ids(self) -> list[int]:
        """Flat id list for the API schema; ordering follows the link table's `position`."""
        return [link.brain_section_id for link in self.brain_links]
