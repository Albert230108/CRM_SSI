import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import ChargesTable from '../components/ChargesTable'
import PaymentsTable from '../components/PaymentsTable'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import type { Beds24Booking, Beds24InvoiceItem, DiscountResult, EditableInvoiceItem } from '../lib/types'

let nextLocalId = 1
function makeLocalId(): string {
  nextLocalId += 1
  return `local-${nextLocalId}`
}

function toEditableItem(item: Beds24InvoiceItem, type: 'charge' | 'payment'): EditableInvoiceItem {
  return {
    localId: makeLocalId(),
    id: item.id,
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

  const [charges, setCharges] = useState<EditableInvoiceItem[]>([])
  const [payments, setPayments] = useState<EditableInvoiceItem[]>([])
  const [originalItemIds, setOriginalItemIds] = useState<string[]>([])

  const [discountResult, setDiscountResult] = useState<DiscountResult | null>(null)
  const [checkingDiscount, setCheckingDiscount] = useState(false)
  const [generatingPdf, setGeneratingPdf] = useState(false)
  const [sending, setSending] = useState(false)

  useEffect(() => {
    if (!bookingId) return
    setLoading(true)
    setError(null)
    apiGet<Beds24Booking>(`/api/booking/${encodeURIComponent(bookingId)}`)
      .then((booking) => {
        setFirstName(firstString(booking.firstName, (booking as Record<string, unknown>).guestFirstName))
        setLastName(firstString(booking.lastName, (booking as Record<string, unknown>).guestLastName))
        setRoomName(firstString(booking.roomName, booking.unitName))
        setPropertyName(firstString(booking.propertyName))
        setCheckIn(firstString((booking as Record<string, unknown>).arrival))
        setCheckOut(firstString((booking as Record<string, unknown>).departure))

        const items = booking.invoiceItems ?? []
        setOriginalItemIds(items.map((item) => item.id).filter((id): id is string => Boolean(id)))
        setCharges(items.filter((item) => item.type === 'charge').map((item) => toEditableItem(item, 'charge')))
        setPayments(items.filter((item) => item.type === 'payment').map((item) => toEditableItem(item, 'payment')))

        const depositItem = items.find((item) => (item.description ?? '').toLowerCase().includes('deposit'))
        if (depositItem) setSecurityDeposit(depositItem.amount ?? 0)
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

  const handleGeneratePdf = async () => {
    if (!bookingId) return
    setGeneratingPdf(true)
    setError(null)
    setNotice(null)
    try {
      const result = await apiPost<{ file_path: string; quotation_number: number }>('/api/quotation/generate-pdf', {
        booking_id: bookingId,
        first_name: firstName,
        last_name: lastName,
        room_name: roomName,
        property_name: propertyName,
        check_in: checkIn,
        check_out: checkOut,
        security_deposit: securityDeposit,
        invoice_items: charges.map((item) => ({
          id: item.id,
          type: item.type,
          description: item.description,
          qty: item.qty,
          amount: item.amount,
          vat_rate: item.vat_rate,
          currency: item.currency,
        })),
        quotation_date: new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }),
      })
      setNotice(`Quotation Q${String(result.quotation_number).padStart(3, '0')} saved to ${result.file_path}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to generate PDF')
    } finally {
      setGeneratingPdf(false)
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
      <h1 className="text-xl font-semibold text-gray-900">Quotation for booking {bookingId}</h1>

      {error ? (
        <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p>
      ) : null}
      {notice ? (
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</p>
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
          <label className="text-xs text-gray-500">
            Property
            <input value={propertyName} onChange={(e) => setPropertyName(e.target.value)} className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm" />
          </label>
          <label className="text-xs text-gray-500">
            Room
            <input value={roomName} onChange={(e) => setRoomName(e.target.value)} className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm" />
          </label>
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
              onChange={(e) => setSecurityDeposit(Number(e.target.value))}
              className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </label>
          <div className="text-xs text-gray-500">
            Nights
            <p className="mt-1 py-1 text-sm text-gray-900">{nights ?? '—'}</p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-gray-500">Discount check</h2>
          <button
            type="button"
            onClick={handleCheckDiscount}
            disabled={checkingDiscount}
            className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {checkingDiscount ? 'Checking...' : 'Check price/discount'}
          </button>
        </div>
        {discountResult ? (
          <div className="mt-2 text-sm text-gray-700">
            <p>Base price: €{discountResult.original_price.toFixed(2)}/night</p>
            <p>Suggested price: €{discountResult.discounted_price.toFixed(2)}/night</p>
            <p className="text-xs text-gray-500">{discountResult.discount_description}</p>
          </div>
        ) : null}
      </div>

      <ChargesTable items={charges} onChange={handleChargeChange} onRemove={handleRemoveCharge} onAdd={handleAddCharge} />
      <PaymentsTable items={payments} />

      <div className="flex gap-3">
        <button
          type="button"
          onClick={handleGeneratePdf}
          disabled={generatingPdf}
          className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-700 disabled:opacity-50"
        >
          {generatingPdf ? 'Generating...' : 'Generate PDF'}
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
