from datetime import date
from typing import Literal

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
    # Display-only VAT-inclusive figures for the quotation form (original_price/
    # discounted_price above stay ex-VAT, matching Settings/the pricing config).
    vat_rate: float = 0.0
    original_price_incl_vat: float = 0.0
    discounted_price_incl_vat: float = 0.0


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


class RecomputeAdminRequest(BaseModel):
    property_name: str
    # Check-in date (YYYY-MM-DD) selects the admin line's VAT rate, matching charge_builder.
    check_in: str
    # The current charge lines from the editor (VAT-inclusive amounts, as the form holds them).
    invoice_items: list[InvoiceItem]


class RecomputeAdminResponse(BaseModel):
    admin_cost_incl: float  # grossed-up, to place on the VAT-inclusive admin charge line
    admin_cost_excl: float
    vat_rate: float
    description: str


class GeneratePdfRequest(BaseModel):
    booking_id: str
    first_name: str
    last_name: str
    room_name: str
    # Beds24 room id, used to render the clickable studio/room pictures link in the PDF
    # (STUDIO_LINK_MAPPING). Optional so a caller that only knows the room name still works.
    room_id: int | None = None
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
    # When true the rendered PDF bytes are also returned (base64) in the response, so a
    # server-to-server caller (the CRM's sales-manager agent) can attach the quotation to the
    # outgoing message without a second round-trip to fetch it back from OneDrive.
    include_content: bool = False
    # "save" (default): write to OneDrive/the tenant folder, as today. "download": render
    # the PDF and hand the bytes straight back - nothing is written anywhere - used by the
    # editor's "Download PDF" button and New Quotation's draft PDF.
    delivery: Literal["save", "download"] = "save"


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
    location: str = "local"  # "onedrive", "local", or "download" (delivery="download": nothing written)
    web_url: str | None = None
    name: str | None = None
    # Populated when the request set include_content=True, or unconditionally for
    # delivery="download" (base64-encoded PDF bytes).
    content_base64: str | None = None


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
    amount: float  # VAT-inclusive (gross) - what actually lands on the quotation/Beds24.
    amount_excl_vat: float = 0.0  # The underlying ex-VAT config value, for reference/debugging.
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


class PaymentPlanExistingRow(BaseModel):
    """A payment row already on the quotation, sent back so a regenerated plan
    can tell which installments were already paid and must not be replaced."""

    description: str
    qty: float = 1
    amount: float = 0
    status: str = "not paid"
    vat_rate: float = 0


class PaymentPlanRequest(BaseModel):
    check_in: date
    check_out: date
    installments: int = Field(1, ge=1, le=24)
    security_deposit: float = 0.0
    charges: list[PaymentPlanChargeLine] = []
    # Current payment rows on the quotation. Any row whose status is a date (i.e. not
    # "not paid") is kept as-is and excluded from regeneration - see payment_plan.build_payment_plan.
    existing_payments: list[PaymentPlanExistingRow] = []


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
    # How much of total_charges is already covered by kept (paid) rows, and what's left.
    kept_count: int = 0
    paid_total: float = 0.0
    remaining: float = 0.0
