import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ChargesTable from '../components/ChargesTable'
import PaymentsTable from '../components/PaymentsTable'
import PropertyRoomFields from '../components/PropertyRoomFields'
import { ApiError, apiGet, apiPost, decodeTokenClaims, getToken } from '../lib/apiClient'
import { isPaymentPaid } from '../lib/payments'
import { downloadBase64Pdf } from '../lib/download'
import {
  LONG_STAY_DEPOSIT_DEFAULT,
  LONG_STAY_DEPOSIT_NIGHT_THRESHOLD,
  ROOM_CAPACITY,
  propertyForRoom,
  roomIdForName,
  roomNameForId,
} from '../lib/constants'
import type {
  Beds24Booking,
  Beds24InvoiceItem,
  BookingGroupResult,
  BuildChargesResult,
  DiscountResult,
  EditableInvoiceItem,
  PaymentPlanResult,
  TenantContext,
} from '../lib/types'

function bookingNights(booking: Beds24Booking): number {
  const arrival = (booking as Record<string, unknown>).arrival
  const departure = (booking as Record<string, unknown>).departure
  if (typeof arrival !== 'string' || typeof departure !== 'string') return 0
  const diff = (new Date(departure).getTime() - new Date(arrival).getTime()) / (1000 * 60 * 60 * 24)
  return Number.isFinite(diff) && diff > 0 ? Math.round(diff) : 0
}

// Shape of the /api/config/prices document we read for the deposit: years -> property ->
// extra_services. Only the deposit fields are typed; everything else on the config is ignored here.
type PropertyExtraServices = { deposit?: number; long_stay_deposit?: number }
type PricingConfig = Record<string, Record<string, { extra_services?: PropertyExtraServices } | undefined>>

// Today's date as DD-Mon-YYYY (e.g. 11-Sep-2026), matching the PDF's DISPLAY_DATE_FMT
// (%d-%b-%Y) so the quotation date reads the same as every other date on the document.
function todayQuotationDate(): string {
  return new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }).replace(/ /g, '-')
}

// The auto-managed Administration costs charge line, matched by description (as the desktop does).
function isAdminCharge(item: { description: string }): boolean {
  return item.description.trim().toLowerCase().includes('administration costs')
}

let nextLocalId = 1
function makeLocalId(): string {
  nextLocalId += 1
  return `local-${nextLocalId}`
}

// Beds24 sends invoice item ids as numbers even though the CRM/quotation API
// schemas type them as strings; coerce here so every id we hold onto (and
// later send back to generate-pdf / send-to-beds24) is a real string.
function normalizeItemId(id: Beds24InvoiceItem['id']): string | undefined {
  return id === undefined || id === null || id === '' ? undefined : String(id)
}

function toEditableItem(item: Beds24InvoiceItem, type: 'charge' | 'payment'): EditableInvoiceItem {
  return {
    localId: makeLocalId(),
    id: normalizeItemId(item.id),
    type,
    description: item.description ?? '',
    qty: item.qty ?? 1,
    amount: item.amount ?? 0,
    vat_rate: item.vatRate ?? 0,
    currency: 'EUR',
    status: item.status,
  }
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

export default function QuotationEditorPage() {
  const { bookingId } = useParams<{ bookingId: string }>()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [roomName, setRoomName] = useState('')
  const [propertyName, setPropertyName] = useState('')
  const [checkIn, setCheckIn] = useState('')
  const [checkOut, setCheckOut] = useState('')
  const [securityDeposit, setSecurityDeposit] = useState(0)
  // Once the operator edits the deposit by hand we stop auto-prefilling it from config,
  // so switching property/dates or re-deriving charges never clobbers a deliberate value.
  const depositManuallyEdited = useRef(false)
  // Fallback only: a deposit amount carried on the loaded booking, used when the per-property
  // config can't resolve a deposit for the selected property/year.
  const carriedDepositRef = useRef<number | null>(null)
  const [pricesConfig, setPricesConfig] = useState<PricingConfig | null>(null)
  const [adults, setAdults] = useState(1)
  const [children, setChildren] = useState(0)
  const [ssiFlag, setSsiFlag] = useState(false)

  const [charges, setCharges] = useState<EditableInvoiceItem[]>([])
  const [payments, setPayments] = useState<EditableInvoiceItem[]>([])
  const [originalItemIds, setOriginalItemIds] = useState<string[]>([])

  const [discountResult, setDiscountResult] = useState<DiscountResult | null>(null)
  const [checkingDiscount, setCheckingDiscount] = useState(false)
  const [generatingPdf, setGeneratingPdf] = useState(false)
  const [downloadingPdf, setDownloadingPdf] = useState(false)
  const [sending, setSending] = useState(false)
  const [buildingCharges, setBuildingCharges] = useState(false)
  const [installments, setInstallments] = useState(1)
  const [buildingPlan, setBuildingPlan] = useState(false)
  const [generatingCombined, setGeneratingCombined] = useState(false)
  const [pdfLink, setPdfLink] = useState<{ url: string; name: string } | null>(null)

  useEffect(() => {
    if (!bookingId) return
    setLoading(true)
    setError(null)
    apiGet<Beds24Booking>(`/api/booking/${encodeURIComponent(bookingId)}`)
      .then(async (booking) => {
        setFirstName(firstString(booking.firstName, (booking as Record<string, unknown>).guestFirstName))
        setLastName(firstString(booking.lastName, (booking as Record<string, unknown>).guestLastName))

        // Beds24 v2 only ever returns roomId/propertyId on the raw booking, not names -
        // fall back through the known room<->id mapping, then the room->property map,
        // before finally asking the CRM for the tenant record this booking belongs to.
        let room = firstString(booking.roomName, booking.unitName) || roomNameForId(booking.roomId)
        let property = firstString(booking.propertyName) || propertyForRoom(room)

        if (!room && !property) {
          const token = getToken()
          const claims = token ? decodeTokenClaims(token) : null
          if (claims?.tenant_id && claims.booking_id === bookingId) {
            try {
              const context = await apiGet<TenantContext>(`/api/booking/tenant-context/${claims.tenant_id}`)
              room = context.room_name ?? room
              property = context.property_name ?? property
            } catch {
              // Best effort only - the fields just stay blank and the user picks them.
            }
          }
        }

        setRoomName(room)
        setPropertyName(property)
        setCheckIn(firstString((booking as Record<string, unknown>).arrival))
        setCheckOut(firstString((booking as Record<string, unknown>).departure))
        setAdults(Number(booking.numAdult ?? 1) || 1)
        setChildren(Number(booking.numChild ?? 0) || 0)

        const items = booking.invoiceItems ?? []
        setOriginalItemIds(items.map((item) => normalizeItemId(item.id)).filter((id): id is string => Boolean(id)))
        setCharges(items.filter((item) => item.type === 'charge').map((item) => toEditableItem(item, 'charge')))
        setPayments(items.filter((item) => item.type === 'payment').map((item) => toEditableItem(item, 'payment')))

        // Deprecated prefill source: a "deposit" invoice item carried over from Beds24 was
        // often a stale/grossed-up value (the ~782 bug). The deposit is now prefilled from the
        // per-property pricing config (see the configuredDeposit effect) instead. We only adopt
        // a carried value as a last resort when the config lookup can't resolve one.
        const depositItem = items.find((item) => (item.description ?? '').toLowerCase().includes('deposit'))
        if (depositItem && depositItem.amount) carriedDepositRef.current = depositItem.amount
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : 'Failed to load booking')
      })
      .finally(() => setLoading(false))
  }, [bookingId])

  const nights = useMemo(() => {
    if (!checkIn || !checkOut) return null
    const diff = (new Date(checkOut).getTime() - new Date(checkIn).getTime()) / (1000 * 60 * 60 * 24)
    return Number.isFinite(diff) && diff > 0 ? Math.round(diff) : null
  }, [checkIn, checkOut])

  const isLongStay = nights !== null && nights > LONG_STAY_DEPOSIT_NIGHT_THRESHOLD

  // Load the per-property pricing config once so the deposit can be prefilled from it.
  useEffect(() => {
    apiGet<PricingConfig>('/api/config/prices')
      .then(setPricesConfig)
      .catch(() => setPricesConfig(null)) // best-effort; falls back to the carried/1500 defaults
  }, [])

  // The deposit for the selected property, per the desktop rule: a normal stay uses the
  // property's configured `deposit`; a long stay (>183 nights) uses its settings-configured
  // `long_stay_deposit` (falling back to LONG_STAY_DEPOSIT_DEFAULT only when unset). Returns
  // null when the config can't resolve the selected property/year.
  const configuredDeposit = useMemo<number | null>(() => {
    if (!pricesConfig || !propertyName) return null
    const year = (checkIn || '').slice(0, 4)
    const years = Object.keys(pricesConfig).sort()
    const yearData = pricesConfig[year] ?? (years.length ? pricesConfig[years[years.length - 1]] : undefined)
    const extra = yearData?.[propertyName]?.extra_services
    if (!extra) return null
    if (isLongStay) return extra.long_stay_deposit ?? LONG_STAY_DEPOSIT_DEFAULT
    return extra.deposit ?? null
  }, [pricesConfig, propertyName, checkIn, isLongStay])

  // Prefill the deposit from config whenever the resolved value changes (property/dates/long-stay),
  // unless the operator has edited it by hand. Falls back to a carried booking deposit, then the
  // long-stay default, so a config-less environment still behaves sensibly.
  useEffect(() => {
    if (depositManuallyEdited.current) return
    const next = configuredDeposit ?? carriedDepositRef.current ?? (isLongStay ? LONG_STAY_DEPOSIT_DEFAULT : null)
    if (next !== null) setSecurityDeposit(next)
  }, [configuredDeposit, isLongStay])

  const occupancy = useMemo(() => {
    const totalGuests = adults + children
    const capacity = ROOM_CAPACITY[roomName]
    if (!capacity || capacity >= 99) return null
    return { totalGuests, capacity, exceeded: totalGuests > capacity }
  }, [adults, children, roomName])

  const chargesTotal = useMemo(
    () => charges.reduce((sum, item) => sum + item.qty * item.amount, 0),
    [charges],
  )
  // Deposit-refund rows are excluded from the payments total, matching the desktop app.
  const paymentsTotal = useMemo(
    () =>
      payments.reduce(
        (sum, item) => (item.description.toLowerCase().includes('refund of deposit') ? sum : sum + item.qty * item.amount),
        0,
      ),
    [payments],
  )
  const balance = useMemo(() => {
    const diff = Math.round((chargesTotal - paymentsTotal) * 100) / 100
    if (Math.abs(diff) <= 0.01) return { state: 'balanced' as const, diff: 0 }
    return { state: paymentsTotal < chargesTotal ? ('under' as const) : ('over' as const), diff: Math.abs(diff) }
  }, [chargesTotal, paymentsTotal])

  const handleChargeChange = (localId: string, patch: Partial<EditableInvoiceItem>) => {
    setCharges((prev) => prev.map((item) => (item.localId === localId ? { ...item, ...patch } : item)))
  }

  const handleAddCharge = () => {
    setCharges((prev) => [
      ...prev,
      { localId: makeLocalId(), type: 'charge', description: '', qty: 1, amount: 0, vat_rate: 0, currency: 'EUR' },
    ])
  }

  const handleRemoveCharge = (localId: string) => {
    setCharges((prev) => prev.filter((item) => item.localId !== localId))
  }

  // Admin costs must stay in sync as other charges change. Unlike the desktop (which only
  // auto-refreshed while status was "Inquiry"), the port recomputes it regardless of status;
  // the backend mirrors charge_builder's admin math so a refresh matches the generated value.
  const chargesRef = useRef<EditableInvoiceItem[]>([])
  chargesRef.current = charges
  const [refreshingAdmin, setRefreshingAdmin] = useState(false)

  const runAdminRecompute = useCallback(async () => {
    const current = chargesRef.current
    const adminLine = current.find(isAdminCharge)
    if (!adminLine || !propertyName || !checkIn) return
    setRefreshingAdmin(true)
    try {
      const result = await apiPost<{ admin_cost_incl: number; vat_rate: number; description: string }>(
        '/api/quotation/recompute-admin',
        {
          property_name: propertyName,
          check_in: checkIn,
          invoice_items: current.map((item) => ({
            type: item.type,
            description: item.description,
            qty: item.qty,
            amount: item.amount,
            vat_rate: item.vat_rate,
            currency: item.currency,
            status: item.status,
          })),
        },
      )
      const newAmount = Math.round(result.admin_cost_incl * 100) / 100
      setCharges((prev) =>
        prev.map((item) =>
          isAdminCharge(item) && (Math.round(item.amount * 100) / 100 !== newAmount || item.vat_rate !== result.vat_rate)
            ? { ...item, qty: 1, amount: newAmount, vat_rate: result.vat_rate }
            : item,
        ),
      )
    } catch {
      // Best-effort: leave the admin line untouched if the recompute call fails.
    } finally {
      setRefreshingAdmin(false)
    }
  }, [propertyName, checkIn])

  // Signature of everything the admin base depends on (all non-admin charges); the admin line
  // itself is excluded so updating it never re-triggers the recompute.
  const nonAdminChargeSignature = useMemo(
    () => JSON.stringify(charges.filter((c) => !isAdminCharge(c)).map((c) => [c.description, c.qty, c.amount, c.vat_rate])),
    [charges],
  )

  useEffect(() => {
    if (!charges.some(isAdminCharge) || !propertyName || !checkIn) return
    const handle = window.setTimeout(() => void runAdminRecompute(), 600)
    return () => window.clearTimeout(handle)
    // Keyed on the non-admin charge signature (not runAdminRecompute, which changes with charges).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonAdminChargeSignature, propertyName, checkIn])

  const handlePaymentChange = (localId: string, patch: Partial<EditableInvoiceItem>) => {
    setPayments((prev) => prev.map((item) => (item.localId === localId ? { ...item, ...patch } : item)))
  }

  const handleAddPayment = () => {
    setPayments((prev) => [
      ...prev,
      { localId: makeLocalId(), type: 'payment', description: '', qty: 1, amount: 0, vat_rate: 0, currency: 'EUR', status: 'not paid' },
    ])
  }

  const handleRemovePayment = (localId: string) => {
    setPayments((prev) => prev.filter((item) => item.localId !== localId))
  }

  const handleAddPaymentPlan = async () => {
    if (!checkIn || !checkOut) {
      setError('Valid check-in and check-out dates are needed to build a payment plan.')
      return
    }
    const hasPaidRows = payments.some((p) => isPaymentPaid(p.status))
    if (
      payments.length > 0 &&
      !window.confirm(
        hasPaidRows
          ? 'Regenerate the plan? Rows with a paid date in Status are kept as-is; unpaid rows are replaced.'
          : 'Replace the current payment rows with the generated plan?',
      )
    ) {
      return
    }
    setBuildingPlan(true)
    setError(null)
    setNotice(null)
    try {
      const result = await apiPost<PaymentPlanResult>('/api/quotation/build-payment-plan', {
        check_in: checkIn,
        check_out: checkOut,
        installments,
        security_deposit: securityDeposit,
        charges: charges.map((c) => ({ description: c.description, qty: c.qty, amount: c.amount })),
        existing_payments: payments.map((p) => ({
          description: p.description,
          qty: p.qty,
          amount: p.amount,
          status: p.status ?? 'not paid',
          vat_rate: p.vat_rate,
        })),
      })
      setPayments(
        result.payments.map((p) => ({
          localId: makeLocalId(),
          type: 'payment' as const,
          description: p.description,
          qty: p.qty,
          amount: p.amount,
          vat_rate: p.vat_rate,
          currency: 'EUR',
          status: p.status,
        })),
      )
      setNotice(
        result.kept_count > 0
          ? `Kept ${result.kept_count} paid row(s); ${result.payments.length - result.kept_count} row(s) regenerated for the remaining €${result.remaining.toFixed(2)}.`
          : `Generated ${result.payments.length} payment rows across ${result.installments} installment(s).`,
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to build payment plan')
    } finally {
      setBuildingPlan(false)
    }
  }

  const handleCheckDiscount = async () => {
    if (!roomName || !propertyName || !nights) {
      setError('Room, property, and valid check-in/check-out dates are needed to check the discount.')
      return
    }
    setCheckingDiscount(true)
    setError(null)
    try {
      const result = await apiPost<DiscountResult>('/api/quotation/discount', {
        room_name: roomName,
        property_name: propertyName,
        nights,
        checkin_date: checkIn,
      })
      setDiscountResult(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to calculate discount')
    } finally {
      setCheckingDiscount(false)
    }
  }

  const handleGenerateCharges = async () => {
    if (!roomName || !propertyName || !checkIn || !checkOut) {
      setError('Room, property, and valid check-in/check-out dates are needed to generate charges.')
      return
    }
    if (charges.length > 0 && !window.confirm('Replace the current charge lines with the standard generated set?')) {
      return
    }
    setBuildingCharges(true)
    setError(null)
    setNotice(null)
    try {
      const result = await apiPost<BuildChargesResult>('/api/quotation/build-charges', {
        property_name: propertyName,
        room_name: roomName,
        check_in: checkIn,
        check_out: checkOut,
        adults,
        children,
        quotation_flag: ssiFlag ? '(SSI)' : null,
      })
      setCharges(
        result.charges.map((c) => ({
          localId: makeLocalId(),
          type: 'charge' as const,
          description: c.description,
          qty: c.qty,
          amount: c.amount,
          vat_rate: c.vat_rate,
          currency: 'EUR',
        })),
      )
      setNotice(result.notes.length ? result.notes.join(' ') : `Generated ${result.charges.length} charge lines.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to generate charges')
    } finally {
      setBuildingCharges(false)
    }
  }

  const handleGeneratePdf = async (delivery: 'save' | 'download') => {
    if (!bookingId) return
    const setLoading = delivery === 'download' ? setDownloadingPdf : setGeneratingPdf
    setLoading(true)
    setError(null)
    setNotice(null)
    setPdfLink(null)
    try {
      const result = await apiPost<{
        file_path: string
        quotation_number: number
        location: string
        web_url?: string | null
        name?: string | null
        content_base64?: string | null
      }>('/api/quotation/generate-pdf', {
        booking_id: bookingId,
        first_name: firstName,
        last_name: lastName,
        room_name: roomName,
        room_id: roomIdForName(roomName),
        property_name: propertyName,
        check_in: checkIn,
        check_out: checkOut,
        security_deposit: securityDeposit,
        // Both charges AND payments, so the PDF's "Proposed payment schedule" reflects the
        // real installment plan/paid status instead of always coming out empty.
        invoice_items: [...charges, ...payments].map((item) => ({
          id: item.id,
          type: item.type,
          description: item.description,
          qty: item.qty,
          amount: item.amount,
          vat_rate: item.vat_rate,
          currency: item.currency,
          status: item.status,
        })),
        quotation_date: todayQuotationDate(),
        delivery,
        include_content: delivery === 'download',
      })
      if (delivery === 'download') {
        if (result.content_base64) {
          downloadBase64Pdf(result.content_base64, result.name || `Quotation_${bookingId}_${String(result.quotation_number).padStart(3, '0')}.pdf`)
        }
        setNotice(`Downloaded quotation Q${String(result.quotation_number).padStart(3, '0')}.`)
      } else {
        const where = result.location === 'onedrive' ? 'OneDrive' : 'the tenant folder'
        setNotice(`Quotation Q${String(result.quotation_number).padStart(3, '0')} saved to ${where}.`)
        if (result.web_url) setPdfLink({ url: result.web_url, name: result.name ?? 'Open in OneDrive' })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to generate PDF')
    } finally {
      setLoading(false)
    }
  }

  const handleGenerateCombinedPdf = async () => {
    if (!bookingId) return
    setGeneratingCombined(true)
    setError(null)
    setNotice(null)
    setPdfLink(null)
    try {
      const group = await apiGet<BookingGroupResult>(`/api/booking/group/${encodeURIComponent(bookingId)}`)
      if (group.bookings.length <= 1) {
        setNotice('This booking is not part of a multi-booking group — use "Generate PDF" instead.')
        return
      }

      const combinedItems: Beds24InvoiceItem[] = []
      const roomNames: string[] = []
      let totalNights = 0
      let totalChargesExclDeposit = 0

      for (const booking of group.bookings) {
        totalNights += bookingNights(booking)
        const rn = firstString(booking.roomName, booking.unitName)
        if (rn && !roomNames.includes(rn)) roomNames.push(rn)
        for (const item of booking.invoiceItems ?? []) {
          combinedItems.push(item)
          if (item.type === 'charge' && !(item.description ?? '').toLowerCase().includes('security deposit')) {
            totalChargesExclDeposit += (item.qty ?? 1) * (item.amount ?? 0)
          }
        }
      }

      const overridePricePerNight = totalNights > 0 ? Math.round((totalChargesExclDeposit / totalNights) * 100) / 100 : 0
      const combinedRoomName = roomNames.length ? roomNames.join(' + ') : roomName

      const result = await apiPost<{ file_path: string; quotation_number: number; location: string; web_url?: string | null; name?: string | null }>('/api/quotation/generate-pdf', {
        booking_id: String(group.master_id ?? bookingId),
        first_name: firstName,
        last_name: lastName,
        room_name: combinedRoomName,
        property_name: propertyName,
        check_in: checkIn,
        check_out: checkOut,
        security_deposit: securityDeposit,
        override_price_per_night: overridePricePerNight,
        override_total_nights: totalNights,
        invoice_items: combinedItems.map((item) => ({
          type: item.type,
          description: item.description ?? '',
          qty: item.qty ?? 1,
          amount: item.amount ?? 0,
          vat_rate: item.vatRate ?? 0,
          currency: 'EUR',
          status: item.status,
        })),
        quotation_date: todayQuotationDate(),
      })
      setNotice(
        `Combined quotation Q${String(result.quotation_number).padStart(3, '0')} for ${group.bookings.length} bookings saved to ${result.location === 'onedrive' ? 'OneDrive' : 'the tenant folder'}.`,
      )
      if (result.web_url) setPdfLink({ url: result.web_url, name: result.name ?? 'Open in OneDrive' })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to generate combined PDF')
    } finally {
      setGeneratingCombined(false)
    }
  }

  const handleSendToBeds24 = async () => {
    if (!bookingId) return
    setSending(true)
    setError(null)
    setNotice(null)
    try {
      await apiPost(`/api/quotation/${encodeURIComponent(bookingId)}/send-to-beds24`, {
        all_original_invoice_item_ids: originalItemIds,
        invoice_items: [...charges, ...payments].map((item) => ({
          id: item.id,
          type: item.type,
          description: item.description,
          qty: item.qty,
          amount: item.amount,
          vat_rate: item.vat_rate,
          currency: item.currency,
          status: item.status,
        })),
      })
      setNotice('Invoice items sent to Beds24. Finance will update shortly in the CRM.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to send to Beds24')
    } finally {
      setSending(false)
    }
  }

  if (loading) {
    return <div className="p-6 text-sm text-gray-500">Loading booking...</div>
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Quotation for booking {bookingId}</h1>
        <button type="button" onClick={() => navigate(-1)} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back
        </button>
      </div>

      {error ? (
        <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p>
      ) : null}
      {notice ? (
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</p>
      ) : null}
      {pdfLink ? (
        <a
          href={pdfLink.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block rounded-lg border border-cyan-600 px-3 py-1.5 text-sm font-medium text-cyan-700 hover:bg-cyan-50"
        >
          Open “{pdfLink.name}” in OneDrive ↗
        </a>
      ) : null}

      <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-gray-500">Guest &amp; stay</h2>
        <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3">
          <label className="text-xs text-gray-500">
            First name
            <input value={firstName} onChange={(e) => setFirstName(e.target.value)} className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm" />
          </label>
          <label className="text-xs text-gray-500">
            Last name
            <input value={lastName} onChange={(e) => setLastName(e.target.value)} className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm" />
          </label>
          <PropertyRoomFields
            propertyName={propertyName}
            roomName={roomName}
            onPropertyChange={setPropertyName}
            onRoomChange={setRoomName}
          />
          <label className="text-xs text-gray-500">
            Check in
            <input type="date" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm" />
          </label>
          <label className="text-xs text-gray-500">
            Check out
            <input type="date" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm" />
          </label>
          <label className="text-xs text-gray-500">
            Security deposit (€)
            <input
              type="number"
              step="0.01"
              value={securityDeposit}
              onChange={(e) => {
                depositManuallyEdited.current = true
                setSecurityDeposit(Number(e.target.value))
              }}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </label>
          <div className="text-xs text-gray-500">
            Nights
            <p className="mt-1 py-1 text-sm text-gray-900">{nights ?? '—'}</p>
          </div>
          <div className="text-xs text-gray-500">
            People
            <p className="mt-1 py-1 text-sm text-gray-900">{adults + children}</p>
          </div>
          <label className="text-xs text-gray-500">
            Adults
            <input
              type="number"
              min={0}
              value={adults}
              onChange={(e) => setAdults(Number(e.target.value))}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </label>
          <label className="text-xs text-gray-500">
            Children
            <input
              type="number"
              min={0}
              value={children}
              onChange={(e) => setChildren(Number(e.target.value))}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-500">
            <input type="checkbox" checked={ssiFlag} onChange={(e) => setSsiFlag(e.target.checked)} />
            SSI registration (municipality cost)
          </label>
        </div>
        {occupancy ? (
          <p className={`mt-2 text-xs font-medium ${occupancy.exceeded ? 'text-rose-600' : 'text-emerald-600'}`}>
            {occupancy.exceeded ? '🔴' : '🟢'} {occupancy.totalGuests}/{occupancy.capacity} guests
            {occupancy.exceeded ? ' — MAX OCCUPANCY EXCEEDED' : ''}
          </p>
        ) : null}
        {isLongStay ? (
          <p className="mt-1 text-xs font-medium text-amber-600">
            Long stay ({nights} nights): the property's long-stay refundable deposit (€{configuredDeposit ?? LONG_STAY_DEPOSIT_DEFAULT}) applies.
          </p>
        ) : null}
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-gray-500">Discount check</h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCheckDiscount}
              disabled={checkingDiscount}
              className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {checkingDiscount ? 'Checking...' : 'Check price/discount'}
            </button>
            <button
              type="button"
              onClick={handleGenerateCharges}
              disabled={buildingCharges}
              className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {buildingCharges ? 'Generating...' : 'Generate standard charges'}
            </button>
            <button
              type="button"
              onClick={() => void runAdminRecompute()}
              disabled={refreshingAdmin || !charges.some(isAdminCharge)}
              className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {refreshingAdmin ? 'Refreshing...' : 'Refresh admin'}
            </button>
          </div>
        </div>
        {discountResult ? (
          <div className="mt-2 text-sm text-gray-700">
            <p>
              Base price: €{discountResult.original_price_incl_vat.toFixed(2)}/night incl. {discountResult.vat_rate}% VAT
              <span className="text-gray-400"> (€{discountResult.original_price.toFixed(2)} excl.)</span>
            </p>
            <p>
              Suggested price: €{discountResult.discounted_price_incl_vat.toFixed(2)}/night incl. {discountResult.vat_rate}% VAT
              <span className="text-gray-400"> (€{discountResult.discounted_price.toFixed(2)} excl.)</span>
            </p>
            <p className="text-xs text-gray-500">{discountResult.discount_description}</p>
          </div>
        ) : null}
      </div>

      <ChargesTable items={charges} onChange={handleChargeChange} onRemove={handleRemoveCharge} onAdd={handleAddCharge} />
      <PaymentsTable
        items={payments}
        onChange={handlePaymentChange}
        onRemove={handleRemovePayment}
        onAdd={handleAddPayment}
        installments={installments}
        onInstallmentsChange={setInstallments}
        onAddPaymentPlan={handleAddPaymentPlan}
        buildingPlan={buildingPlan}
        onAutoCountInstallments={
          nights !== null ? () => setInstallments(Math.max(1, Math.min(Math.floor(nights / 30) + 1, 24))) : undefined
        }
      />

      <div
        className={`rounded-xl border p-3 text-sm font-medium ${
          balance.state === 'balanced'
            ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
            : balance.state === 'under'
              ? 'border-rose-200 bg-rose-50 text-rose-700'
              : 'border-amber-200 bg-amber-50 text-amber-700'
        }`}
      >
        {balance.state === 'balanced'
          ? '✓ Charges and payments are balanced'
          : balance.state === 'under'
            ? `⚠️ Payments are €${balance.diff.toFixed(2)} less than charges`
            : `⚠️ Payments are €${balance.diff.toFixed(2)} more than charges`}
      </div>

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => handleGeneratePdf('save')}
          disabled={generatingPdf}
          className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-700 disabled:opacity-50"
        >
          {generatingPdf ? 'Saving...' : 'Save PDF to tenant folder'}
        </button>
        <button
          type="button"
          onClick={() => handleGeneratePdf('download')}
          disabled={downloadingPdf}
          className="rounded-lg border border-cyan-600 px-4 py-2 text-sm font-medium text-cyan-700 hover:bg-cyan-50 disabled:opacity-50"
        >
          {downloadingPdf ? 'Downloading...' : 'Download PDF'}
        </button>
        <button
          type="button"
          onClick={handleGenerateCombinedPdf}
          disabled={generatingCombined}
          className="rounded-lg border border-cyan-600 px-4 py-2 text-sm font-medium text-cyan-700 hover:bg-cyan-50 disabled:opacity-50"
          title="For grouped bookings: one PDF combining every booking in the group"
        >
          {generatingCombined ? 'Building...' : 'Combined PDF (group)'}
        </button>
        <button
          type="button"
          onClick={handleSendToBeds24}
          disabled={sending}
          className="rounded-lg bg-gray-800 px-4 py-2 text-sm font-medium text-white hover:bg-gray-900 disabled:opacity-50"
        >
          {sending ? 'Sending...' : 'Send to Beds24'}
        </button>
      </div>
    </div>
  )
}
