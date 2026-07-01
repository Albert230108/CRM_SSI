import { useEffect, useMemo, useState } from 'react'
import { useAuthStore } from '../store/authStore'

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
  }
  charges: FinanceItem[]
  payments: FinanceItem[]
}

type TenantSummary = FinanceResponse['tenant']

type FinanceBoxProps = {
  tenantId?: number
}

export default function FinanceBox({ tenantId }: FinanceBoxProps) {
  const token = useAuthStore((state) => state.token)
  const [charges, setCharges] = useState<FinanceItem[]>([])
  const [payments, setPayments] = useState<FinanceItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [tenant, setTenant] = useState<TenantSummary | null>(null)

  useEffect(() => {
    if (!tenantId) {
      setCharges([])
      setPayments([])
      setError('')
      setTenant(null)
      setLoading(false)
      return
    }

    const controller = new AbortController()
    const loadFinance = async () => {
      try {
        setLoading(true)
        setError('')
        const [financeResponse, tenantResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/tenants/${tenantId}/finance`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
          fetch(`${API_BASE_URL}/api/tenants/${tenantId}`, {
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
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load finance data')
      } finally {
        setLoading(false)
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

  const getPropertyForRoom = (roomName: string | null): string | null => {
    if (!roomName) return null
    const entry = Object.entries(PROPERTY_ROOMS).find(([, rooms]) => rooms.includes(roomName))
    return entry ? entry[0] : null
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

  const formatDisplayDate = (value?: string | null): string => {
    if (!value) return 'Not set'
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString()
  }

  const summaryRoomName = tenant?.room_name || tenant?.roomName || roomIdToName(tenant?.room_id ?? tenant?.roomId ?? tenant?.accommodation_id ?? tenant?.accommodationId) || null
  const summaryProperty = getPropertyForRoom(summaryRoomName) || 'Unknown property'
  const summaryRoom = summaryRoomName || 'Unknown room'
  const summaryName = getDisplayGuestName(tenant)
  const summaryCheckIn = formatDisplayDate(tenant?.check_in)
  const summaryCheckOut = formatDisplayDate(tenant?.check_out)

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
    <div className="space-y-5">
      <div>
        <p className="text-xs uppercase tracking-[0.35em] text-cyan-600">Finance</p>
        <h2 className="mt-1 text-xl font-semibold text-gray-900">Payments and charges</h2>
        <p className="mt-1 text-sm text-gray-500">{tenantId ? (summaryName || `Booking ${tenantId}`) : 'Select a tenant to view finance data'}</p>
      </div>

      {loading ? <p className="text-sm text-gray-500">Loading finance...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      {!tenantId ? null : (
        <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
            <p className="text-xs uppercase tracking-[0.25em] text-gray-500">Booking summary</p>
            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Full name</p>
                <p className="mt-1 text-sm font-medium text-gray-900">{summaryName}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Property</p>
                <p className="mt-1 text-sm font-medium text-gray-900">{summaryProperty}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Room</p>
                <p className="mt-1 text-sm font-medium text-gray-900">{summaryRoom}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Check in</p>
                <p className="mt-1 text-sm font-medium text-gray-900">{summaryCheckIn}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Check out</p>
                <p className="mt-1 text-sm font-medium text-gray-900">{summaryCheckOut}</p>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between gap-4">
            <div className="flex gap-4 text-sm">
              <span className="text-emerald-600">+ Payments {totals.payments.toFixed(2)}</span>
              <span className="text-rose-500">- Charges {Math.abs(totals.charges).toFixed(2)}</span>
            </div>
            <p className="text-sm font-semibold text-cyan-700">Balance {totals.total.toFixed(2)}</p>
          </div>

          <div className="mt-4 overflow-hidden rounded-xl border border-gray-200">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="bg-gray-50 text-xs uppercase tracking-[0.2em] text-gray-500">
                <tr>
                  <th className="px-3 py-3">Date</th>
                  <th className="px-3 py-3">Description</th>
                  <th className="px-3 py-3">Amount</th>
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
                        <td className="px-3 py-3 text-gray-500">
                          {new Date(item.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-3 py-3 text-gray-900">{item.description || 'Charge'}</td>
                        <td className="px-3 py-3 font-medium text-rose-600">
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
                        <td className="px-3 py-3 text-gray-500">
                          {new Date(item.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-3 py-3 text-gray-900">{item.description || 'Payment'}</td>
                        <td className="px-3 py-3 font-medium text-emerald-600">
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
