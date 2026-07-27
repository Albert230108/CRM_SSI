from datetime import date

from pydantic import BaseModel


class DiscountRequest(BaseModel):
    room_name: str
    property_name: str
    nights: int
    checkin_date: date | None = None


class DiscountResponse(BaseModel):
    original_price: float
    discounted_price: float
    discount_per_night: float
    discount_description: str
    rule_applied: str | None = None
    rule_type: str | None = None
    priority: int
    base_price_source: str
    tier_price: float
    using_tier_price: bool


class AdminCostsRequest(BaseModel):
    property_name: str
    total_charges: float
    deposit_amount: float = 0.0
    city_tax_amount: float = 0.0


class AdminCostsResponse(BaseModel):
    admin_cost: float
    base_amount: float
    raw_admin_cost: float
    percentage: float
    min_limit: float
    max_limit: float
    clamped: bool
    description: str
    property_name: str


class InvoiceItem(BaseModel):
    id: str | None = None
    type: str  # "charge" or "payment"
    description: str
    qty: float = 1
    amount: float
    vat_rate: float = 0
    currency: str = "EUR"
    status: str | None = None


class GeneratePdfRequest(BaseModel):
    booking_id: str
    first_name: str
    last_name: str
    room_name: str
    property_name: str | None = None
    check_in: str
    check_out: str
    security_deposit: float = 0.0
    invoice_items: list[InvoiceItem]
    quotation_date: str


class SendToBeds24Request(BaseModel):
    all_original_invoice_item_ids: list[str]
    invoice_items: list[InvoiceItem]


class VatSplitRequest(BaseModel):
    start_date: date
    end_date: date
    price_per_night: float


class VatSplitSegment(BaseModel):
    start: date
    end: date
    vat: int
    price: float
    nights: int
    unit_price: float


class GeneratePdfResponse(BaseModel):
    file_path: str
    quotation_number: int
