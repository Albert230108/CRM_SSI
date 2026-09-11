export interface TenantContext {
  tenant_id: number
  booking_id: string
  name: string
  first_name: string | null
  last_name: string | null
  room_id: number | null
  room_name: string | null
  property_name: string | null
  check_in: string | null
  check_out: string | null
}

export interface Beds24Booking {
  id: string
  roomId?: number | string
  propertyId?: number | string
  roomName?: string
  unitName?: string
  propertyName?: string
  firstName?: string
  lastName?: string
  arrival?: string
  departure?: string
  numAdult?: number
  numChild?: number
  invoiceItems?: Beds24InvoiceItem[]
  [key: string]: unknown
}

export interface Beds24InvoiceItem {
  id?: string
  type: string
  description?: string
  qty?: number
  amount?: number
  vatRate?: number
  status?: string
}

/** Editable line item used in the quotation editor's charges/payments tables. */
export interface EditableInvoiceItem {
  localId: string
  id?: string
  type: 'charge' | 'payment'
  description: string
  qty: number
  amount: number
  vat_rate: number
  currency: string
  status?: string
}

export interface DiscountResult {
  original_price: number
  discounted_price: number
  discount_per_night: number
  discount_description: string
  rule_applied: string | null
  rule_type: string | null
  priority: number
  base_price_source: string
  tier_price: number
  using_tier_price: boolean
  // Display-only VAT-inclusive figures for the quotation form; original_price/
  // discounted_price above stay ex-VAT, matching Settings/the pricing config.
  vat_rate: number
  original_price_incl_vat: number
  discounted_price_incl_vat: number
}

export interface GeneratedCharge {
  kind: string
  description: string
  qty: number
  amount: number  // VAT-inclusive (gross) - what lands on the quotation/Beds24.
  amount_excl_vat: number  // The underlying ex-VAT config value, for reference.
  vat_rate: number
  detail: string | null
}

export interface BuildChargesResult {
  nights: number
  total_guests: number
  charges: GeneratedCharge[]
  notes: string[]
}

export interface GeneratedPayment {
  kind: string
  description: string
  status: string
  qty: number
  amount: number
  vat_rate: number
}

export interface PaymentPlanResult {
  installments: number
  total_charges: number
  payments: GeneratedPayment[]
  kept_count: number
  paid_total: number
  remaining: number
}

export interface BookingGroupResult {
  master_id: string | number | null
  bookings: Beds24Booking[]
}
