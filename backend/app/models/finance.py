from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, func

from app.database import Base


class Finance(Base):
    __tablename__ = "finances"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    type = Column(String(10), nullable=False, default="charge")
    amount = Column(Numeric(12, 2), nullable=False)
    # Per-line breakdown so the charges table can show qty / unit price / VAT% / total columns.
    # `amount` stays the line total (qty * unit_price) for back-compat; these are nullable for rows
    # imported before the columns existed.
    qty = Column(Numeric(12, 2), nullable=True)
    unit_price = Column(Numeric(12, 2), nullable=True)
    vat_rate = Column(Numeric(5, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="EUR")
    description = Column(Text, nullable=True)
    # Per-line Beds24 invoice-item status (e.g. paid/unpaid); nullable for rows imported
    # before this column existed and for non-Beds24 finance rows that carry no status.
    status = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

