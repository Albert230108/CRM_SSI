import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type Booking = {
  booking_id: string
  name: string | null
  first_name: string | null
  last_name: string | null
  check_in: string | null
  check_out: string | null
  booking_status: string | null
  imported: boolean
}

type ImportModalProps = {
  open: boolean
  onClose: () => void
}

export default function ImportModal({ open, onClose }: ImportModalProps) {
  const token = useAuthStore((state) => state.token)
  const [bookings, setBookings] = useState<Booking[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [importingId, setImportingId] = useState<string | null>(null)

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
        if (!response.ok) throw new Error('Failed to load Beds24 bookings')
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
    try {
      setImportingId(bookingId)
      const response = await fetch(`${API_BASE_URL}/api/tenants/import/${bookingId}`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!response.ok) throw new Error('Import failed')
      setBookings((current) => current.map((booking) => (booking.booking_id === bookingId ? { ...booking, imported: true } : booking)))
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
                  <p className="text-base font-semibold text-gray-900">{booking.name ?? booking.booking_id}</p>
                  <p className="mt-1 text-sm text-gray-500">Booking ID {booking.booking_id}</p>
                  <p className="mt-1 text-sm text-gray-500">{booking.booking_status || 'Unknown status'}</p>
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
                    onClick={() => handleImport(booking.booking_id)}
                    className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500"
                  >
                    {importingId === booking.booking_id ? 'Importing...' : 'Import'}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
