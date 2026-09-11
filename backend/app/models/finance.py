from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, func

from app.database import Base


class Finance(Base):
    __tablename__ = "finances"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    type = Column(String(10), nullable=False, default="charge")
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="EUR")
    description = Column(Text, nullable=True)
    # Per-line Beds24 invoice-item status (e.g. paid/unpaid); nullable for rows imported
    # before this column existed and for non-Beds24 finance rows that carry no status.
    status = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

