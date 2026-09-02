from datetime import date

from pydantic import BaseModel, Field


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
    # For combined (group) quotations: pre-computed price/night and total nights
    # across all bookings, so the PDF's derived figures reflect the whole group.
    override_price_per_night: float | None = None
    override_total_nights: int | None = None


class SendToBeds24Request(BaseModel):
    all_original_invoice_item_ids: list[str]
    invoice_items: list[InvoiceItem]


class CreateBookingRequest(BaseModel):
    room_id: int
    arrival: str
    departure: str
    status: str = "inquiry"
    first_name: str
    last_name: str = ""
    email: str = ""
    phone: str = ""
    num_adults: int = Field(1, ge=0)
    num_children: int = Field(0, ge=0)
    flag_text: str | None = None
    company_info: str | None = None
    invoice_items: list[InvoiceItem] = []


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
    location: str = "local"  # "onedrive" or "local"
    web_url: str | None = None
    name: str | None = None


class BuildChargesRequest(BaseModel):
    property_name: str
    room_name: str
    check_in: date
    check_out: date
    adults: int = Field(1, ge=0)
    children: int = Field(0, ge=0)
    quotation_flag: str | None = None  # "(SSI)" -> Municipality Cost instead of Citytax


class GeneratedCharge(BaseModel):
    kind: str
    description: str
    qty: float
    amount: float
    vat_rate: float
    detail: str | None = None


class BuildChargesResponse(BaseModel):
    nights: int
    total_guests: int
    charges: list[GeneratedCharge]
    notes: list[str] = []


class PaymentPlanChargeLine(BaseModel):
    description: str
    qty: float = 1
    amount: float = 0


class PaymentPlanRequest(BaseModel):
    check_in: date
    check_out: date
    installments: int = Field(1, ge=1, le=24)
    security_deposit: float = 0.0
    charges: list[PaymentPlanChargeLine] = []


class GeneratedPayment(BaseModel):
    kind: str
    description: str
    status: str = "not paid"
    qty: float = 1
    amount: float
    vat_rate: float = 0


class PaymentPlanResponse(BaseModel):
    installments: int
    total_charges: float
    payments: list[GeneratedPayment]
