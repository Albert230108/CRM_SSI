import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatDisplayDate } from '../lib/date'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

const ROOM_ID_MAPPING: Record<string, number> = {
  House: 271050,
  'Studio 1': 262377,
  'Studio 2': 262375,
  'Studio 3': 262379,
  'Studio 4': 262376,
  'Studio 5': 262380,
  'Studio 6': 262378,
  'Room 1': 262576,
  'Room 2': 262578,
  'Room 3': 262579,
  'Room 4': 262580,
  'Room 5': 262581,
  'Under Request': 564014,
  'Ground floor': 389957,
  'Upper floor': 564867,
  'Duplex Apartment': 286739,
}

const PROPERTY_ROOMS: Record<string, string[]> = {
  'Central-Day Inn': ['Studio 1', 'Studio 2', 'Studio 3', 'Studio 4', 'Studio 5', 'Studio 6'],
  'Ensche-Day Inn': ['Room 1', 'Room 2', 'Room 3', 'Room 4', 'Room 5'],
  'Guest information': ['Under Request'],
  'Hoogstraat 69': ['Ground floor', 'Upper floor'],
  'Blekerstraat': ['House'],
  'Atjehstraat': ['Duplex Apartment'],
}

const ROOM_NAME_BY_ID = Object.fromEntries(Object.entries(ROOM_ID_MAPPING).map(([roomName, roomId]) => [roomId, roomName]))

type FinanceItem = {
  id: number
  type: 'charge' | 'payment'
  amount: string
  currency: string
  description: string | null
  created_at: string
}

type FinanceResponse = {
  tenant: {
    id: number
    booking_id: string
    name?: string | null
    first_name?: string | null
    last_name?: string | null
    check_in?: string | null
    check_out?: string | null
    room_id?: number | string | null
    roomId?: number | string | null
    room_name?: string | null
    roomName?: string | null
    accommodation_id?: number | string | null
    accommodationId?: number | string | null
    property_name?: string | null
    propertyName?: string | null
    property?: string | null
    booking_status?: string | null
    referer?: string | null
    beds24_raw?: Record<string, unknown> | null
    email?: string | null
    phone?: string | null
    mobile?: string | null
  }
  charges: FinanceItem[]
  payments: FinanceItem[]
}

type TenantSummary = FinanceResponse['tenant']

type WhatsappEndpointOption = {
  id: number
  tenant_id: number
  channel_type: string
  provider: string
  external_account_id: string | null
  external_phone_id: string | null
  external_chat_namespace: string | null
  chat_display_name: string | null
  routing_strategy: string
  is_active: boolean
}

const RAW_WHATSAPP_ID_PATTERN = /^\d+@(lid|c\.us|g\.us|s\.whatsapp\.net)$/i

const formatWhatsappEndpointLabel = (endpoint: WhatsappEndpointOption) => {
  if (endpoint.chat_display_name && !RAW_WHATSAPP_ID_PATTERN.test(endpoint.chat_display_name.trim())) {
    return endpoint.chat_display_name
  }
  if (endpoint.external_account_id) return endpoint.external_account_id
  return `Endpoint ${endpoint.id}`
}

const digitsOnly = (value: string | null | undefined): string | null => {
  if (!value) return null
  const digits = value.replace(/\D/g, '')
  return digits.length >= 8 ? digits : null
}

// WhatsApp's real phone number can't be recovered for @lid chats (they're opaque linked-device
// ids, not phone numbers) -- fall back to a phone-looking display name for that specific chat.
// The tenant's own phone/mobile is only used when there's no linked chat at all (endpoint is
// null): it must never substitute for a specific chat that can't be resolved, since every
// unresolvable chat would then collapse to that same number, making the chat selection meaningless.
const resolveWhatsappTarget = (
  endpoint: WhatsappEndpointOption | null,
  tenant: TenantSummary | null,
): { url: string; targeted: boolean } => {
  const namespaceMatch = endpoint?.external_chat_namespace?.match(/^(\d+)@(c\.us|s\.whatsapp\.net)$/i)
  const resolvedPhone = endpoint
    ? (namespaceMatch ? namespaceMatch[1] : null) ?? digitsOnly(endpoint.chat_display_name)
    : digitsOnly(tenant?.phone) ?? digitsOnly(tenant?.mobile)

  if (resolvedPhone) {
    return { url: `https://web.whatsapp.com/send?phone=${resolvedPhone}`, targeted: true }
  }
  return { url: 'https://web.whatsapp.com/', targeted: false }
}

type FinanceBoxProps = {
  tenantId?: number
  onReady?: (tenantId: number) => void
}

export default function FinanceBox({ tenantId, onReady }: FinanceBoxProps) {
  const token = useAuthStore((state) => state.token)
  const [charges, setCharges] = useState<FinanceItem[]>([])
  const [payments, setPayments] = useState<FinanceItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [tenant, setTenant] = useState<TenantSummary | null>(null)
  const [whatsappEndpoints, setWhatsappEndpoints] = useState<WhatsappEndpointOption[]>([])
  const [showWhatsappMenu, setShowWhatsappMenu] = useState(false)
  const [showQuoteNotice, setShowQuoteNotice] = useState(false)
  const whatsappMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!showWhatsappMenu) return
    const handleClickOutside = (event: MouseEvent) => {
      if (whatsappMenuRef.current && !whatsappMenuRef.current.contains(event.target as Node)) {
        setShowWhatsappMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showWhatsappMenu])

  useEffect(() => {
    if (!tenantId) {
      setCharges([])
      setPayments([])
      setError('')
      setTenant(null)
      setWhatsappEndpoints([])
      setLoading(false)
      return
    }

    const controller = new AbortController()
    const activeTenantId = tenantId
    const loadFinance = async () => {
      try {
        setLoading(true)
        setError('')
        const [financeResponse, tenantResponse, whatsappResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/tenants/${tenantId}/finance`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
          fetch(`${API_BASE_URL}/api/tenants/${tenantId}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
          fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/whatsapp-endpoints`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
        ])
        if (!financeResponse.ok) throw new Error('Failed to load finance data')
        const data: FinanceResponse = await financeResponse.json()
        setCharges(data.charges ?? [])
        setPayments(data.payments ?? [])
        if (tenantResponse.ok) {
          const tenantData: TenantSummary = await tenantResponse.json()
          setTenant(tenantData)
        } else {
          setTenant(null)
        }
        if (whatsappResponse.ok) {
          const endpoints: WhatsappEndpointOption[] = await whatsappResponse.json()
          setWhatsappEndpoints(endpoints.filter((endpoint) => endpoint.is_active))
        } else {
          setWhatsappEndpoints([])
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load finance data')
      } finally {
        setLoading(false)
        onReady?.(activeTenantId)
      }
    }

    loadFinance()
    return () => controller.abort()
  }, [tenantId, token])

  const roomIdToName = (value: number | string | null | undefined) => {
    if (value === null || value === undefined || value === '') return null
    const numericValue = typeof value === 'number' ? value : Number(value)
    if (Number.isFinite(numericValue)) {
      return ROOM_NAME_BY_ID[numericValue] || null
    }
    return null
  }

  const getPropertyForRoom = (roomName: string | null, propertyName?: string | null): string | null => {
    const explicitProperty = propertyName?.trim()
    if (explicitProperty) return explicitProperty
    if (!roomName) return null
    const entry = Object.entries(PROPERTY_ROOMS).find(([, rooms]) => rooms.includes(roomName))
    return entry ? entry[0] : null
  }

  const readFirstString = (...values: unknown[]): string | null => {
    for (const value of values) {
      if (typeof value === 'string' && value.trim()) return value.trim()
    }
    return null
  }

  const readRoomAndProperty = (tenantData: TenantSummary | null) => {
    const raw = tenantData?.beds24_raw
    const rawObject = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null
    const rawRoomName = rawObject
      ? readFirstString(
          rawObject.roomName,
          rawObject.room_name,
          rawObject.unitName,
          rawObject.unit_name,
          rawObject.propName,
          rawObject.propertyName,
          rawObject.property_name,
          rawObject.unit,
        )
      : null
    const rawPropertyName = rawObject
      ? readFirstString(
          rawObject.propertyName,
          rawObject.property_name,
          rawObject.propName,
          rawObject.property,
        )
      : null
    const roomName = readFirstString(
      tenantData?.room_name,
      tenantData?.roomName,
      rawRoomName,
      roomIdToName(tenantData?.room_id ?? tenantData?.roomId ?? tenantData?.accommodation_id ?? tenantData?.accommodationId),
    )
    const propertyName = readFirstString(
      tenantData?.property_name,
      tenantData?.propertyName,
      tenantData?.property,
      rawPropertyName,
      getPropertyForRoom(roomName, rawPropertyName),
    )
    return { roomName, propertyName }
  }

  const getRawField = (tenantData: TenantSummary | null, ...keys: string[]): string | null => {
    const raw = tenantData?.beds24_raw
    const rawObject = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null
    if (!rawObject) return null
    return readFirstString(...keys.map((key) => rawObject[key]))
  }

  const getDisplayGuestName = (tenantData: TenantSummary | null): string => {
    if (!tenantData) return 'Unknown guest'
    const firstName = tenantData.first_name?.trim() || ''
    const lastName = tenantData.last_name?.trim() || ''
    const combinedName = [firstName, lastName].filter(Boolean).join(' ').trim()
    if (combinedName) return combinedName
    if (tenantData.name?.trim()) return tenantData.name.trim()
    return 'Unknown guest'
  }

  const roomSummary = readRoomAndProperty(tenant)
  const summaryRoomName = roomSummary.roomName
  const summaryProperty = roomSummary.propertyName || 'Unknown property'
  const summaryRoom = summaryRoomName || 'Unknown room'
  const summaryName = getDisplayGuestName(tenant)
  const summaryCheckIn = formatDisplayDate(tenant?.check_in)
  const summaryCheckOut = formatDisplayDate(tenant?.check_out)
  const summaryBookingId = tenant?.booking_id || 'Unknown'
  const summaryStatus = tenant?.booking_status || getRawField(tenant, 'status') || 'Unknown'
  const summarySubStatus = getRawField(tenant, 'subStatus') || 'N/A'
  const summaryReferer = tenant?.referer || getRawField(tenant, 'referer') || 'Unknown'
  const summaryRefererEditable = getRawField(tenant, 'refererEditable') || 'Unknown'

  const hasTenantPhoneFallback = Boolean(digitsOnly(tenant?.phone) || digitsOnly(tenant?.mobile))
  const whatsappAvailable = whatsappEndpoints.length > 0 || hasTenantPhoneFallback
  const gmailUrl = tenant?.email
    ? `https://mail.google.com/mail/u/0/#search/from:(${encodeURIComponent(tenant.email)})`
    : 'https://mail.google.com/mail/u/0/'

  const openWhatsappTarget = (endpoint: WhatsappEndpointOption | null) => {
    const { url } = resolveWhatsappTarget(endpoint, tenant)
    window.open(url, '_blank', 'noopener,noreferrer')
    setShowWhatsappMenu(false)
  }

  const handleWhatsappClick = () => {
    if (whatsappEndpoints.length > 1) {
      setShowWhatsappMenu((prev) => !prev)
      return
    }
    if (whatsappEndpoints.length === 1) {
      openWhatsappTarget(whatsappEndpoints[0])
      return
    }
    if (hasTenantPhoneFallback) {
      openWhatsappTarget(null)
    }
  }

  const handleQuoteClick = () => {
    setShowQuoteNotice(true)
    window.setTimeout(() => setShowQuoteNotice(false), 2000)
  }

  const totals = useMemo(() => {
    const totalPayments = payments.reduce((sum, item) => {
      const amount = Number(item.amount)
      return Number.isFinite(amount) ? sum + amount : sum
    }, 0)
    const totalCharges = charges.reduce((sum, item) => {
      const amount = Number(item.amount)
      return Number.isFinite(amount) ? sum + amount : sum
    }, 0)
    return {
      payments: totalPayments,
      charges: totalCharges,
      total: totalPayments - totalCharges,
    }
  }, [charges, payments])

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xl font-semibold text-gray-900">Tenant Info</h2>
        <div className="flex items-center gap-2">
          <div className="relative" ref={whatsappMenuRef}>
            <button
              type="button"
              onClick={handleWhatsappClick}
              disabled={!whatsappAvailable}
              title={whatsappAvailable ? 'Open WhatsApp' : 'No WhatsApp number linked to this tenant'}
              className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-white"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current text-emerald-600">
                <path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5.1-1.3A10 10 0 1 0 12 2zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1-.2.2-.7.8-.8 1-.2.2-.3.2-.5.1-.2-.1-1-.4-1.9-1.2-.7-.6-1.2-1.4-1.3-1.6-.2-.2 0-.4.1-.5.1-.1.2-.3.4-.4.1-.2.2-.3.2-.5.1-.2 0-.4 0-.5-.1-.1-.6-1.4-.8-2-.2-.5-.4-.4-.6-.4h-.5c-.2 0-.5.1-.7.3-.2.2-.9.9-.9 2.2s1 2.6 1.1 2.8c.1.2 2 3 4.8 4.2.7.3 1.2.5 1.6.6.7.2 1.3.2 1.8.1.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.2-1.2-.1-.1-.2-.2-.5-.3z" />
              </svg>
              WhatsApp
            </button>
            {showWhatsappMenu && whatsappEndpoints.length > 1 ? (
              <div className="absolute right-0 z-10 mt-1 w-56 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                {whatsappEndpoints.map((endpoint) => (
                  <button
                    key={endpoint.id}
                    type="button"
                    onClick={() => openWhatsappTarget(endpoint)}
                    className="block w-full truncate px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-50"
                  >
                    {formatWhatsappEndpointLabel(endpoint)}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <a
            href={gmailUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="Open Gmail"
            className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current text-rose-500">
              <path d="M20 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 2-8 5-8-5h16zM4 18V7.4l8 5 8-5V18H4z" />
            </svg>
            Gmail
          </a>
          <div className="relative">
            <button
              type="button"
              onClick={handleQuoteClick}
              title="Quotation Manager"
              className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current text-cyan-700">
                <path d="M7 2h8l5 5v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm7 1.5V8h4.5L14 3.5zM8 13h8v1.5H8V13zm0 3.5h8V18H8v-1.5zm0-7h4v1.5H8V9.5z" />
              </svg>
              Quote
            </button>
            {showQuoteNotice ? (
              <div className="absolute right-0 z-10 mt-1 whitespace-nowrap rounded-lg border border-gray-200 bg-gray-900 px-3 py-1.5 text-xs font-medium text-white shadow-lg">
                Quotation Manager — coming soon
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {loading ? <p className="text-sm text-gray-500">Loading finance...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      {!tenantId ? null : (
        <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.25em] text-gray-500">Summary</p>
              {tenant?.booking_id ? (
                <a
                  href={`https://beds24.com/control2.php?ajax=bookedit&id=${encodeURIComponent(tenant.booking_id)}&tab=1`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs font-medium text-cyan-700 hover:underline"
                >
                  Open in Beds24
                </a>
              ) : null}
            </div>
            <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 md:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Booking ID</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryBookingId}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Full name</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryName}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Property</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryProperty}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Room</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryRoom}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Check in</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryCheckIn}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Check out</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryCheckOut}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Status</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryStatus}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Sub-status</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summarySubStatus}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Original referer</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryReferer}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Referer</p>
                <p className="mt-0.5 break-words text-sm font-medium text-gray-900">{summaryRefererEditable}</p>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between gap-4">
            <div className="flex gap-4 text-sm">
              <span className="text-emerald-600">Payments {totals.payments.toFixed(2)}</span>
              <span className="text-rose-500">Charges {Math.abs(totals.charges).toFixed(2)}</span>
            </div>
            <p className="text-sm font-semibold text-cyan-700">Balance {totals.total.toFixed(2)}</p>
          </div>

          <div className="mt-3 overflow-hidden rounded-xl border border-gray-200">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="bg-gray-50 text-xs uppercase tracking-[0.2em] text-gray-500">
                <tr>
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Description</th>
                  <th className="px-3 py-2">Amount</th>
                </tr>
              </thead>
              <tbody>
                {charges.length === 0 && payments.length === 0 && !loading ? (
                  <tr>
                    <td className="px-3 py-4 text-gray-500" colSpan={3}>No finance entries found.</td>
                  </tr>
                ) : null}
                {charges.length > 0 ? (
                  <>
                    <tr className="bg-rose-50">
                      <td colSpan={3} className="px-3 py-2 text-xs font-semibold uppercase tracking-widest text-rose-500">
                        Charges
                      </td>
                    </tr>
                    {charges.map((item) => (
                      <tr key={item.id} className="border-t border-gray-200">
                        <td className="px-3 py-2 text-gray-500">
                          {formatDisplayDate(item.created_at)}
                        </td>
                        <td className="px-3 py-2 text-gray-900">{item.description || 'Charge'}</td>
                        <td className="px-3 py-2 font-medium text-rose-600">
                          {item.currency} {Number(item.amount).toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </>
                ) : null}
                {payments.length > 0 ? (
                  <>
                    <tr className="bg-emerald-50">
                      <td colSpan={3} className="px-3 py-2 text-xs font-semibold uppercase tracking-widest text-emerald-600">
                        Payments
                      </td>
                    </tr>
                    {payments.map((item) => (
                      <tr key={item.id} className="border-t border-gray-200">
                        <td className="px-3 py-2 text-gray-500">
                          {formatDisplayDate(item.created_at)}
                        </td>
                        <td className="px-3 py-2 text-gray-900">{item.description || 'Payment'}</td>
                        <td className="px-3 py-2 font-medium text-emerald-600">
                          {item.currency} {Number(item.amount).toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

