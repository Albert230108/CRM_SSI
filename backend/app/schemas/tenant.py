from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TenantCreate(BaseModel):
    booking_id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    city: str | None = None
    country: str | None = None
    zip_code: str | None = None
    address: str | None = None
    company: str | None = None
    language: str | None = None
    num_adults: int | None = None
    num_children: int | None = None
    num_nights: int | None = None
    arrival_time: str | None = None
    departure_time: str | None = None
    room_name: str | None = None
    property_name: str | None = None
    source: str | None = None
    referer: str | None = None
    total_price: float | None = None
    commission: float | None = None
    deposit: float | None = None
    currency: str | None = None
    beds24_raw: dict | None = None
    room_id: int | None = None
    notes: str | None = None
    booking_status: str | None = None
    name: str
    responsible_comm: str | None = None


class TenantRead(BaseModel):
    id: int
    booking_id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    city: str | None = None
    country: str | None = None
    zip_code: str | None = None
    address: str | None = None
    company: str | None = None
    language: str | None = None
    num_adults: int | None = None
    num_children: int | None = None
    num_nights: int | None = None
    arrival_time: str | None = None
    departure_time: str | None = None
    room_name: str | None = None
    property_name: str | None = None
    source: str | None = None
    referer: str | None = None
    total_price: float | None = None
    commission: float | None = None
    deposit: float | None = None
    currency: str | None = None
    beds24_raw: dict | None = None
    room_id: int | None = None
    notes: str | None = None
    draft_notes: str | None = None
    booking_status: str | None = None
    name: str
    responsible_comm: str | None = None
    created_at: datetime
    updated_at: datetime
    last_message_date: datetime | None = None
    last_message_channel: str | None = None
    last_message_direction: str | None = None
    unread_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class Beds24BookingPreview(BaseModel):
    booking_id: str
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    city: str | None = None
    country: str | None = None
    zip_code: str | None = None
    address: str | None = None
    company: str | None = None
    language: str | None = None
    num_adults: int | None = None
    num_children: int | None = None
    num_nights: int | None = None
    arrival_time: str | None = None
    departure_time: str | None = None
    room_name: str | None = None
    property_name: str | None = None
    source: str | None = None
    referer: str | None = None
    original_referer: str | None = None
    total_price: float | None = None
    commission: float | None = None
    deposit: float | None = None
    currency: str | None = None
    room_id: int | None = None
    notes: str | None = None
    booking_status: str | None = None
    responsible_comm: str | None = None
    booking_time: str | None = None
    modified_time: str | None = None
    imported: bool = False

