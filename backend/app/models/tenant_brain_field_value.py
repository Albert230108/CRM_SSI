from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from app.database import Base


class TenantBrainFieldValue(Base):
    """One tenant's value for one BrainFieldDefinition field.

    A row only exists once a value has been set (manually or by the brain writer) - a field
    with no evidence yet for a tenant simply has no row, rather than a row holding null.
    """

    __tablename__ = "tenant_brain_field_values"
    __table_args__ = (
        UniqueConstraint("tenant_id", "field_definition_id", name="uq_tenant_brain_field_values_tenant_field"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    field_definition_id = Column(
        Integer, ForeignKey("brain_field_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value = Column(Text, nullable=True)
    source = Column(String(20), nullable=False)  # manual | planner | scanner
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
