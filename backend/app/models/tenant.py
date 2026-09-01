from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, Numeric, String, Text, func, text

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
    draft_notes = Column(Text, nullable=True)
    booking_status = Column(String(100), nullable=True)
    name = Column(String(255), nullable=False, index=True)
    responsible_comm = Column(Text, nullable=True)
    auto_add_shared_email_threads = Column(Boolean, nullable=False, server_default=text("true"))
    # Marks a freshly imported/created tenant so the sidebar shows a "New" badge. Cleared on the
    # first outbound message to the tenant (see communications.send_tenant_communication) or when
    # the operator manually dismisses it (see tenants.dismiss_tenant_new).
    is_new = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())




    @property
    def property_name(self) -> str | None:
        raw = self.beds24_raw or {}
        if isinstance(raw, dict):
            value = raw.get("propertyName") or raw.get("property_name") or raw.get("propName") or raw.get("property")
            if isinstance(value, str) and value.strip():
                return value.strip()
        if self.room_name in {"Studio 1", "Studio 2", "Studio 3", "Studio 4", "Studio 5", "Studio 6"}:
            return "Central-Day Inn"
        if self.room_name in {"Room 1", "Room 2", "Room 3", "Room 4", "Room 5"}:
            return "Ensche-Day Inn"
        if self.room_name == "Under Request":
            return "Guest information"
        if self.room_name in {"Ground floor", "Upper floor"}:
            return "Hoogstraat 69"
        if self.room_name == "House":
            return "Blekerstraat"
        if self.room_name == "Duplex Apartment":
            return "Atjehstraat"
        return None
