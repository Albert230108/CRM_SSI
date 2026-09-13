// Keeps a negative "Refund of Deposit ..." payment row in sync with the security-deposit field,
// live, as the operator edits the deposit - ported from the desktop's
// manage_security_deposit_refund_in_table. The row's description matches the backend's
// payment_plan._deposit_refund_row exactly, so a plan rebuilt server-side reuses this same row
// instead of appending a duplicate.

import type { EditableInvoiceItem } from './types'

const REFUND_DESC_PREFIX = 'Refund of Deposit (Provided No Damages Are Present); due: '

export function isDepositRefundRow(description: string): boolean {
  return description.toLowerCase().includes('refund of deposit')
}

// check-out + 7 days as DD-Mon-YYYY (e.g. 10-Mar-2026), matching the backend's _DATE_FMT (%d-%b-%Y).
// Parses the ISO date by parts to avoid a UTC/local off-by-one shift.
function formatRefundDate(checkOutIso: string): string {
  const parts = checkOutIso.split('-').map(Number)
  if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return ''
  const [year, month, day] = parts
  const d = new Date(year, month - 1, day)
  d.setDate(d.getDate() + 7)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).replace(/ /g, '-')
}

// Returns a payments array with the deposit-refund row upserted (deposit > 0) or removed
// (deposit <= 0). Returns the SAME array reference when nothing needs to change, so a React
// setPayments(prev => syncDepositRefundRow(prev, ...)) bails out instead of re-rendering/looping.
export function syncDepositRefundRow(
  payments: EditableInvoiceItem[],
  deposit: number,
  checkOut: string,
  makeLocalId: () => string,
): EditableInvoiceItem[] {
  const existing = payments.filter((p) => isDepositRefundRow(p.description))
  const hasDeposit = deposit > 0 && Boolean(checkOut)

  if (!hasDeposit) {
    return existing.length ? payments.filter((p) => !isDepositRefundRow(p.description)) : payments
  }

  const description = `${REFUND_DESC_PREFIX}${formatRefundDate(checkOut)}`
  const amount = -(Math.round(deposit * 100) / 100)
  const prior = existing[0]

  if (
    existing.length === 1 &&
    prior.description === description &&
    prior.amount === amount &&
    prior.qty === 1 &&
    prior.vat_rate === 0
  ) {
    return payments // already correct - no state churn
  }

  const row: EditableInvoiceItem = {
    localId: prior?.localId ?? makeLocalId(),
    id: prior?.id,
    type: 'payment',
    description,
    qty: 1,
    amount,
    vat_rate: 0,
    currency: 'EUR',
    status: prior?.status ?? 'not paid',
  }
  // Drop any existing refund row(s) and append the single canonical one at the end (as the desktop).
  return [...payments.filter((p) => !isDepositRefundRow(p.description)), row]
}
