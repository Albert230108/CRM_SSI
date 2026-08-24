from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class MemoryQaMessage(Base):
    """One turn of the persisted "ask AI about this tenant's memory" chat, shown in the Tenant
    Brain tab so staff can scroll back through past questions."""

    __tablename__ = "memory_qa_messages"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    asked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
