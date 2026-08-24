from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.database import Base


class BrainFieldDefinition(Base):
    """One field in the global structured working-memory schema.

    Admin-authored: `ai_instruction` tells the brain writer what evidence to look for. Every
    tenant tries to fill the same set of fields - see TenantBrainFieldValue for the per-tenant
    values this schema is filled into.
    """

    __tablename__ = "brain_field_definitions"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(80), nullable=False, unique=True, index=True)
    label = Column(String(255), nullable=False)
    ai_instruction = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
