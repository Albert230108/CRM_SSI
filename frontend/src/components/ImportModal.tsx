import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type Booking = {
  booking_id: string
  name: string | null
  first_name: string | null
  last_name: string | null
  email: string | null
  phone: string | null
  mobile: string | null
  check_in: string | null
  check_out: string | null
  notes: string | null
  booking_status: string | null
  responsible_comm: string | null
  imported: boolean
}

type ImportModalProps = {
  open: boolean
  onClose: () => void
  onImported?: () => void
}

export default function ImportModal({ open, onClose, onImported }: ImportModalProps) {
  const token = useAuthStore((state) => state.token)
  const [bookings, setBookings] = useState<Booking[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [importingId, setImportingId] = useState<string | null>(null)
  const [confirmBooking, setConfirmBooking] = useState<Booking | null>(null)
  const [editFields, setEditFields] = useState<Partial<Booking>>({})

  useEffect(() => {
    if (!open) return

    const controller = new AbortController()
    const loadBookings = async () => {
      try {
        setLoading(true)
        setError('')
        const response = await fetch(`${API_BASE_URL}/api/beds24/bookings`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        })
        if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error((payload && typeof payload === 'object' && 'detail' in payload && typeof payload.detail === 'string') ? payload.detail : 'Failed to load Beds24 bookings')
      }
        const data: Booking[] = await response.json()
        setBookings(data)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load Beds24 bookings')
      } finally {
        setLoading(false)
      }
    }

    loadBookings()
    return () => controller.abort()
  }, [open, token])

  const handleImport = async (bookingId: string) => {
    const booking = bookings.find((item) => item.booking_id === bookingId)
    if (!booking) return
    try {
      setImportingId(bookingId)
      const body = {
        booking_id: bookingId,
        name: [editFields.first_name, editFields.last_name].filter(Boolean).join(' ').trim() || booking.name || bookingId,
        first_name: (editFields.first_name as string) || booking.first_name || null,
        last_name: (editFields.last_name as string) || booking.last_name || null,
        email: (editFields.email as string) || booking.email || null,
        phone: (editFields.phone as string) || booking.phone || null,
        mobile: (editFields.mobile as string) || booking.mobile || null,
        check_in: booking.check_in || null,
        check_out: booking.check_out || null,
        notes: booking.notes || null,
        booking_status: (editFields.booking_status as string) || booking.booking_status || null,
        responsible_comm: (editFields.responsible_comm as string) || booking.responsible_comm || null,
      }
      const response = await fetch(`${API_BASE_URL}/api/tenants/import`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error((payload && typeof payload === 'object' && 'detail' in payload && typeof payload.detail === 'string') ? payload.detail : 'Import failed')
      }
      setBookings((current) => current.map((item) => (item.booking_id === bookingId ? { ...item, imported: true } : item)))
      setConfirmBooking(null)
      setEditFields({})
      onImported?.()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImportingId(null)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 px-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-cyan-600">Beds24</p>
            <h2 className="mt-1 text-2xl font-semibold text-gray-900">Import bookings</h2>
          </div>
          <button type="button" onClick={onClose} className="text-sm text-gray-500 hover:text-gray-900">
            Close
          </button>
        </div>

        {loading ? <p className="mt-6 text-sm text-gray-500">Loading bookings...</p> : null}
        {error ? <p className="mt-6 text-sm text-rose-400">{error}</p> : null}

        <div className="mt-6 max-h-[60vh] space-y-3 overflow-y-auto pr-1">
          {bookings.map((booking) => (
            <div key={booking.booking_id} className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-base font-semibold text-gray-900">
                    {booking.name ?? <span className="italic text-gray-400">No name (ID: {booking.booking_id})</span>}
                  </p>
                  <p className="mt-1 text-sm text-gray-500">Booking ID {booking.booking_id}</p>
                  <p className="mt-1 text-sm text-gray-500">{booking.booking_status || 'Unknown status'}</p>
                  {booking.responsible_comm && (
                    <p className="mt-1 text-sm text-cyan-600">Responsible: {booking.responsible_comm}</p>
                  )}
                </div>

                <div className="flex items-center gap-3">
                  {booking.imported ? (
                    <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-300">
                      Already Imported
                    </span>
                  ) : null}
                  <button
                    type="button"
                    disabled={booking.imported || importingId === booking.booking_id}
                    onClick={() => {
                      setConfirmBooking(booking)
                      setEditFields({
                        first_name: booking.first_name ?? '',
                        last_name: booking.last_name ?? '',
                        email: booking.email ?? '',
                        phone: booking.phone ?? '',
                        mobile: booking.mobile ?? '',
                        booking_status: booking.booking_status ?? '',
                        responsible_comm: booking.responsible_comm ?? '',
                      })
                    }}
                    className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500"
                  >
                    Import
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {confirmBooking && (
          <div className="fixed inset-0 z-60 flex items-center justify-center bg-gray-900/50 px-4 backdrop-blur-sm">
            <div className="w-full max-w-lg rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
              <h3 className="mb-4 text-xl font-semibold text-gray-900">Confirm import</h3>
              <p className="mb-6 text-xs text-gray-400">
                Review and edit fields before importing.
              </p>
              <div className="mb-4 rounded-xl bg-gray-100 px-3 py-2">
                <p className="text-xs text-gray-400">Booking ID</p>
                <p className="text-sm font-medium text-gray-700">{confirmBooking.booking_id}</p>
              </div>
              <div className="mb-4 rounded-xl bg-gray-100 px-3 py-2">
                <p className="text-xs text-gray-400">Full name (auto-composed from first + last)</p>
                <p className="text-sm font-medium text-gray-700">{[editFields.first_name, editFields.last_name].filter(Boolean).join(' ') || '?'}</p>
              </div>
              <div className="max-h-[55vh] overflow-y-auto pr-1">
              {([
                ['first_name', 'First name'],
                ['last_name', 'Last name'],
                ['email', 'Email address'],
                ['phone', 'Phone (tel)'],
                ['mobile', 'Phone (mobile)'],
                ['booking_status', 'Status'],
                ['responsible_comm', 'Responsible person'],
              ] as [keyof Booking, string][]).map(([field, label]) => (
                <div key={field} className="mb-3">
                  <label className="mb-1 block text-xs text-gray-500">{label}</label>
                  <input
                    type="text"
                    value={(editFields[field] as string) ?? ''}
                    onChange={(e) => setEditFields((prev) => ({ ...prev, [field]: e.target.value }))}
                    className="w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                  />
                </div>
              ))}
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setConfirmBooking(null)}
                  className="rounded-xl px-4 py-2 text-sm text-gray-500 hover:text-gray-900"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={importingId === confirmBooking.booking_id}
                  onClick={() => handleImport(confirmBooking.booking_id)}
                  className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
                >
                  {importingId === confirmBooking.booking_id ? 'Importing...' : 'Confirm import'}
                </button>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}




