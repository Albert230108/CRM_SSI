from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

SOURCE_USER = "user"
SOURCE_AI = "ai"


class AppKnowledgeEntry(Base):
    """One entry in the growing "how the CRM works" knowledge base the assistant searches.

    Entries start as either a staff member typing one directly, or the assistant proposing a
    `knowledge_suggestion` that a staff member reviews and saves - the assistant never writes
    here on its own (see ai_assistant_service.py). `source` records which path created it so the
    knowledge tab can flag AI-authored entries for a second look.
    """

    __tablename__ = "app_knowledge_entries"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    source = Column(String(10), nullable=False, default=SOURCE_USER, server_default=SOURCE_USER)  # user | ai
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
