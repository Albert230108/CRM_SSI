from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.database import Base

SOURCE_MANUAL = "manual"
SOURCE_PLANNER = "planner"
SOURCE_SCANNER = "scanner"


class TenantBrainEntry(Base):
    """One remembered fact about a tenant, kept as its own row so it can be edited or deleted
    independently of the rest of the tenant's working memory.
    """

    __tablename__ = "tenant_brain_entries"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    source = Column(String(20), nullable=False)  # manual | planner | scanner
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
