import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import BalanceBanner from '../components/BalanceBanner'
import ChargesTable from '../components/ChargesTable'
import FlagField from '../components/FlagField'
import PropertyRoomFields from '../components/PropertyRoomFields'
import PaymentsTable from '../components/PaymentsTable'
import { ApiError, apiGet, apiPost } from '../lib/apiClient'
import { syncDepositRefundRow } from '../lib/depositRefund'
import { autoInstallments } from '../lib/installments'
import { isPaymentPaid } from '../lib/payments'
import { resolveConfiguredDeposit, type PricingConfig } from '../lib/pricing'
import { downloadBase64Pdf } from '../lib/download'
import {
  LONG_STAY_DEPOSIT_DEFAULT,
  LONG_STAY_DEPOSIT_NIGHT_THRESHOLD,
  PROPERTY_ROOMS,
  ROOM_CAPACITY,
  ROOM_ID_MAPPING,
  SSI_FLAG,
} from '../lib/constants'
import type { BuildChargesResult, EditableInvoiceItem, PaymentPlanResult } from '../lib/types'

let nextLocalId = 1
function makeLocalId(): string {
  nextLocalId += 1
  return `new-${nextLocalId}`
}

const PROPERTIES = Object.keys(PROPERTY_ROOMS)
const STATUS_OPTIONS = ['inquiry', 'request', 'confirmed']

export default function NewQuotationPage() {
  const navigate = useNavigate()

  const [propertyName, setPropertyName] = useState(PROPERTIES[0])
  const [roomName, setRoomName] = useState(PROPERTY_ROOMS[PROPERTIES[0]][0])
  const [status, setStatus] = useState('inquiry')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [checkIn, setCheckIn] = useState('')
  const [checkOut, setCheckOut] = useState('')
  const [adults, setAdults] = useState(1)
  const [children, setChildren] = useState(0)
  const [securityDeposit, setSecurityDeposit] = useState(0)
  // Once the operator edits the deposit by hand, stop auto-prefilling it from config.
  const depositManuallyEdited = useRef(false)
  const [flagText, setFlagText] = useState('')
  const [companyInfo, setCompanyInfo] = useState('')

  const [charges, setCharges] = useState<EditableInvoiceItem[]>([])
  const [payments, setPayments] = useState<EditableInvoiceItem[]>([])
  const [installments, setInstallments] = useState(1)
  const [pricesConfig, setPricesConfig] = useState<PricingConfig | null>(null)

  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [buildingCharges, setBuildingCharges] = useState(false)
  const [buildingPlan, setBuildingPlan] = useState(false)
  const [creating, setCreating] = useState(false)
  const [downloadingPdf, setDownloadingPdf] = useState(false)

  const nights = useMemo(() => {
    if (!checkIn || !checkOut) return null
    const diff = (new Date(checkOut).getTime() - new Date(checkIn).getTime()) / (1000 * 60 * 60 * 24)
    return Number.isFinite(diff) && diff > 0 ? Math.round(diff) : null
  }, [checkIn, checkOut])

  const isLongStay = nights !== null && nights > LONG_STAY_DEPOSIT_NIGHT_THRESHOLD

  const occupancy = useMemo(() => {
    const totalGuests = adults + children
    const capacity = ROOM_CAPACITY[roomName]
    if (!capacity || capacity >= 99) return null
    return { totalGuests, capacity, exceeded: totalGuests > capacity }
  }, [adults, children, roomName])

  const chargesTotal = useMemo(() => charges.reduce((sum, item) => sum + item.qty * item.amount, 0), [charges])
  const paymentsTotal = useMemo(
    () =>
      payments.reduce(
        (sum, item) => (item.description.toLowerCase().includes('refund of deposit') ? sum : sum + item.qty * item.amount),
        0,
      ),
    [payments],
  )

  // Load the per-property pricing config once so the deposit can be prefilled from it.
  useEffect(() => {
    apiGet<PricingConfig>('/api/config/prices')
      .then(setPricesConfig)
      .catch(() => setPricesConfig(null)) // best-effort; deposit just stays whatever is entered
  }, [])

  // The configured deposit for the selected property/room/date (long-stay -> €1500), same rule as
  // the editor + desktop.
  const configuredDeposit = useMemo<number | null>(
    () => resolveConfiguredDeposit(pricesConfig, propertyName, roomName, checkIn, nights),
    [pricesConfig, propertyName, roomName, checkIn, nights],
  )

  // Prefill the deposit from config unless the operator has edited it by hand.
  useEffect(() => {
    if (depositManuallyEdited.current) return
    if (configuredDeposit !== null) setSecurityDeposit(configuredDeposit)
  }, [configuredDeposit])

  // Keep the negative "Refund of Deposit" row in sync with the deposit field, live. Keyed on the
  // deposit/check-out only (not payments) so it can't loop; returns the same array when unchanged.
  useEffect(() => {
    setPayments((prev) => syncDepositRefundRow(prev, securityDeposit, checkOut, makeLocalId))
  }, [securityDeposit, checkOut])

  const handleChargeChange = (localId: string, patch: Partial<EditableInvoiceItem>) =>
    setCharges((prev) => prev.map((item) => (item.localId === localId ? { ...item, ...patch } : item)))
  const handleAddCharge = () =>
    setCharges((prev) => [
      ...prev,
      { localId: makeLocalId(), type: 'charge', description: '', qty: 1, amount: 0, vat_rate: 0, currency: 'EUR' },
    ])
  const handleRemoveCharge = (localId: string) => setCharges((prev) => prev.filter((item) => item.localId !== localId))

  const handlePaymentChange = (localId: string, patch: Partial<EditableInvoiceItem>) =>
    setPayments((prev) => prev.map((item) => (item.localId === localId ? { ...item, ...patch } : item)))
  const handleAddPayment = () =>
    setPayments((prev) => [
      ...prev,
      { localId: makeLocalId(), type: 'payment', description: '', qty: 1, amount: 0, vat_rate: 0, currency: 'EUR', status: 'not paid' },
    ])
  const handleRemovePayment = (localId: string) => setPayments((prev) => prev.filter((item) => item.localId !== localId))

  // Core standard-charge generation. Replaces the full charge set and returns it (React state isn't
  // visible synchronously, so the auto path passes the result straight into the plan builder).
  const generateStandardCharges = useCallback(async (): Promise<EditableInvoiceItem[] | null> => {
    if (!roomName || !propertyName || !checkIn || !checkOut) return null
    setBuildingCharges(true)
    setError(null)
    try {
      const result = await apiPost<BuildChargesResult>('/api/quotation/build-charges', {
        property_name: propertyName,
        room_name: roomName,
        check_in: checkIn,
        check_out: checkOut,
        adults,
        children,
        quotation_flag: flagText === SSI_FLAG ? SSI_FLAG : null,
      })
      const generated = result.charges.map((c) => ({
        localId: makeLocalId(),
        type: 'charge' as const,
        description: c.description,
        qty: c.qty,
        amount: c.amount,
        vat_rate: c.vat_rate,
        currency: 'EUR',
      }))
      setCharges(generated)
      return generated
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to generate charges')
      return null
    } finally {
      setBuildingCharges(false)
    }
  }, [propertyName, roomName, checkIn, checkOut, adults, children, flagText])

  const handleGenerateCharges = async () => {
    if (!roomName || !propertyName || !checkIn || !checkOut) {
      setError('Property, room, and valid dates are needed to generate charges.')
      return
    }
    if (charges.length > 0 && !window.confirm('Replace the current charge lines with the standard generated set?')) return
    setNotice(null)
    const generated = await generateStandardCharges()
    if (generated) setNotice(`Generated ${generated.length} charge lines.`)
  }

  // Core plan build, taking charges/installments explicitly so the auto path can pass freshly
  // generated charges. Keeps already-paid rows (existing_payments).
  const buildPaymentPlanFrom = async (
    chargeItems: EditableInvoiceItem[],
    installmentCount: number,
    { silent = false }: { silent?: boolean } = {},
  ) => {
    if (!checkIn || !checkOut) {
      if (!silent) setError('Valid check-in and check-out dates are needed to build a payment plan.')
      return
    }
    setBuildingPlan(true)
    if (!silent) setError(null)
    try {
      const result = await apiPost<PaymentPlanResult>('/api/quotation/build-payment-plan', {
        check_in: checkIn,
        check_out: checkOut,
        installments: installmentCount,
        security_deposit: securityDeposit,
        charges: chargeItems.map((c) => ({ description: c.description, qty: c.qty, amount: c.amount })),
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
      if (!silent) {
        setNotice(
          result.kept_count > 0
            ? `Kept ${result.kept_count} paid row(s); ${result.payments.length - result.kept_count} row(s) regenerated for the remaining €${result.remaining.toFixed(2)}.`
            : `Generated ${result.payments.length} payment rows.`,
        )
      }
    } catch (err) {
      if (!silent) setError(err instanceof ApiError ? err.message : 'Failed to build payment plan')
    } finally {
      setBuildingPlan(false)
    }
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
    )
      return
    setNotice(null)
    await buildPaymentPlanFrom(charges, installments, { silent: false })
  }

  // Auto-build the standard charges whenever the stay inputs change (and all are present) - the New
  // page builds from scratch, so the first complete form auto-generates without the button. Also
  // auto-selects installments (nights//30+1) and, for an Inquiry, rebuilds the payment plan.
  useEffect(() => {
    if (!roomName || !propertyName || !checkIn || !checkOut) return
    const handle = window.setTimeout(async () => {
      const nextInstallments = autoInstallments(nights, installments)
      setInstallments(nextInstallments)
      const newCharges = await generateStandardCharges()
      if (status === 'inquiry' && newCharges) {
        await buildPaymentPlanFrom(newCharges, nextInstallments, { silent: true })
      }
    }, 700)
    return () => window.clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propertyName, roomName, checkIn, checkOut, adults, children])

  const handleDownloadPdf = async () => {
    if (!checkIn || !checkOut) {
      setError('Valid check-in and check-out dates are needed to download a PDF.')
      return
    }
    setDownloadingPdf(true)
    setError(null)
    setNotice(null)
    try {
      const result = await apiPost<{ quotation_number: number; name?: string | null; content_base64?: string | null }>(
        '/api/quotation/generate-pdf',
        {
          booking_id: 'Draft',
          first_name: firstName,
          last_name: lastName,
          room_name: roomName,
          property_name: propertyName,
          check_in: checkIn,
          check_out: checkOut,
          security_deposit: securityDeposit,
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
          quotation_date: new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }),
          delivery: 'download',
          include_content: true,
        },
      )
      if (result.content_base64) {
        downloadBase64Pdf(result.content_base64, result.name || `Quotation_Draft_${String(result.quotation_number).padStart(3, '0')}.pdf`)
      }
      setNotice('Downloaded a draft PDF. Nothing was written to Beds24.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to download PDF')
    } finally {
      setDownloadingPdf(false)
    }
  }

  const handleCreate = async () => {
    const roomId = ROOM_ID_MAPPING[roomName]
    if (!roomId) {
      setError(`No Beds24 room id is known for "${roomName}".`)
      return
    }
    if (!firstName.trim() || !checkIn || !checkOut) {
      setError('First name and valid check-in/check-out dates are required.')
      return
    }
    if (!window.confirm('This creates a NEW booking in Beds24. Continue?')) return
    setCreating(true)
    setError(null)
    setNotice(null)
    try {
      const result = await apiPost<{ booking_id: string }>('/api/quotation/create-booking', {
        room_id: roomId,
        arrival: checkIn,
        departure: checkOut,
        status,
        first_name: firstName,
        last_name: lastName,
        email,
        phone,
        num_adults: adults,
        num_children: children,
        flag_text: flagText || null,
        company_info: companyInfo.trim() || null,
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
      navigate(`/${encodeURIComponent(result.booking_id)}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create booking')
    } finally {
      setCreating(false)
    }
  }

  const inputClass = 'mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm'

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">New quotation</h1>
        <button type="button" onClick={() => navigate('/')} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back
        </button>
      </div>

      {error ? <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</p> : null}

      <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-gray-500">Booking</h2>
        <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3">
          <PropertyRoomFields propertyName={propertyName} roomName={roomName} onPropertyChange={setPropertyName} onRoomChange={setRoomName} />
          <label className="text-xs text-gray-500">
            Status
            <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputClass}>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-500">
            First name
            <input value={firstName} onChange={(e) => setFirstName(e.target.value)} className={inputClass} />
          </label>
          <label className="text-xs text-gray-500">
            Last name
            <input value={lastName} onChange={(e) => setLastName(e.target.value)} className={inputClass} />
          </label>
          <label className="text-xs text-gray-500">
            Email
            <input value={email} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
          </label>
          <label className="text-xs text-gray-500">
            Phone
            <input value={phone} onChange={(e) => setPhone(e.target.value)} className={inputClass} />
          </label>
          <label className="text-xs text-gray-500">
            Check in
            <input type="date" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} className={inputClass} />
          </label>
          <label className="text-xs text-gray-500">
            Check out
            <input type="date" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} className={inputClass} />
          </label>
          <label className="text-xs text-gray-500">
            Adults
            <input type="number" min={0} value={adults} onChange={(e) => setAdults(Number(e.target.value))} className={inputClass} />
          </label>
          <label className="text-xs text-gray-500">
            Children
            <input type="number" min={0} value={children} onChange={(e) => setChildren(Number(e.target.value))} className={inputClass} />
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
              className={inputClass}
            />
          </label>
          <div className="text-xs text-gray-500">
            Nights
            <p className="mt-1 py-1 text-sm text-gray-900">{nights ?? '—'}</p>
          </div>
          <FlagField value={flagText} onChange={setFlagText} />
          <label className="col-span-2 text-xs text-gray-500 md:col-span-3">
            Company info (optional)
            <textarea value={companyInfo} onChange={(e) => setCompanyInfo(e.target.value)} className={inputClass} rows={2} />
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
            Long stay ({nights} nights): a fixed €{LONG_STAY_DEPOSIT_DEFAULT} refundable deposit applies.
          </p>
        ) : null}
        <div className="mt-3">
          <button
            type="button"
            onClick={handleGenerateCharges}
            disabled={buildingCharges}
            className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {buildingCharges ? 'Generating...' : 'Generate standard charges'}
          </button>
        </div>
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
      />

      <BalanceBanner chargesTotal={chargesTotal} paymentsTotal={paymentsTotal} />

      <div className="flex gap-3">
        <button
          type="button"
          onClick={handleCreate}
          disabled={creating}
          className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-700 disabled:opacity-50"
        >
          {creating ? 'Creating booking...' : 'Create booking in Beds24'}
        </button>
        <button
          type="button"
          onClick={handleDownloadPdf}
          disabled={downloadingPdf}
          title="Renders and downloads a PDF from this form. Nothing is written to Beds24."
          className="rounded-lg border border-cyan-600 px-4 py-2 text-sm font-medium text-cyan-700 hover:bg-cyan-50 disabled:opacity-50"
        >
          {downloadingPdf ? 'Downloading...' : 'Download PDF (draft)'}
        </button>
      </div>
    </div>
  )
}
