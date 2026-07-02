from sqlalchemy import Column, DateTime, Integer, JSON, Numeric, String, Text, func

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(String(100), nullable=False, unique=True, index=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(100), nullable=True)
    mobile = Column(String(100), nullable=True)
    check_in = Column(String(50), nullable=True)
    check_out = Column(String(50), nullable=True)
    city = Column(String(255), nullable=True)
    country = Column(String(100), nullable=True)
    zip_code = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    company = Column(String(255), nullable=True)
    language = Column(String(50), nullable=True)
    num_adults = Column(Integer, nullable=True)
    num_children = Column(Integer, nullable=True)
    num_nights = Column(Integer, nullable=True)
    arrival_time = Column(String(50), nullable=True)
    departure_time = Column(String(50), nullable=True)
    room_name = Column(String(255), nullable=True)
    source = Column(String(255), nullable=True)
    referer = Column(String(500), nullable=True)
    total_price = Column(Numeric(12, 2), nullable=True)
    commission = Column(Numeric(12, 2), nullable=True)
    deposit = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(10), nullable=True)
    beds24_raw = Column(JSON, nullable=True)
    room_id = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    booking_status = Column(String(100), nullable=True)
    name = Column(String(255), nullable=False, index=True)
    responsible_comm = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())



