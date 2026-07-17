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
  room_name: string | null
  property_name: string | null
  booking_time?: string | null
  modified_time?: string | null
  referer: string | null
  original_referer: string | null
}

type ImportModalProps = {
  open: boolean
  onClose: () => void
  onImported?: () => void
}

function getErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = 'detail' in payload ? (payload as { detail?: unknown }).detail : undefined
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'detail' in detail && typeof (detail as { detail?: unknown }).detail === 'string') {
    return (detail as { detail: string }).detail
  }
  return fallback
}

async function readJsonSafely(response: Response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function pollGmailSyncJob(jobId: string, token: string | null, onDone: () => void) {
  const intervalId = window.setInterval(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/sync-status/${jobId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      const data = await readJsonSafely(response)
      if (!response.ok || data?.status === 'done' || data?.status === 'error') {
        window.clearInterval(intervalId)
        if (data?.status === 'done') onDone()
      }
    } catch {
      window.clearInterval(intervalId)
    }
  }, 3000)
}

export default function ImportModal({ open, onClose, onImported }: ImportModalProps) {
  const token = useAuthStore((state) => state.token)
  const [bookings, setBookings] = useState<Booking[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [importingId, setImportingId] = useState<string | null>(null)
  const [confirmBooking, setConfirmBooking] = useState<Booking | null>(null)
  const [editFields, setEditFields] = useState<Partial<Booking>>({})
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkImporting, setBulkImporting] = useState(false)
  const [filterResponsible, setFilterResponsible] = useState<string | null>(null)
  const [filterStatus, setFilterStatus] = useState<string | null>(null)
  const [filterRecentDays, setFilterRecentDays] = useState<number | null>(null)
  const [filterRecentField, setFilterRecentField] = useState<'booking_time' | 'modified_time'>('booking_time')
  const [filterCheckInStart, setFilterCheckInStart] = useState('')
  const [filterCheckInEnd, setFilterCheckInEnd] = useState('')

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
          const payload = await readJsonSafely(response)
          throw new Error(getErrorMessage(payload, 'Failed to load Beds24 bookings'))
        }
        const data = await readJsonSafely(response)
        if (!Array.isArray(data)) {
          throw new Error('Beds24 bookings response was malformed')
        }
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

  const handleImport = async (bookingId: string, overrides: Partial<Booking> = {}) => {
    const booking = bookings.find((item) => item.booking_id === bookingId)
    if (!booking) return
    try {
      setImportingId(bookingId)
      const body = {
        booking_id: bookingId,
        name: [overrides.first_name, overrides.last_name].filter(Boolean).join(' ').trim() || booking.name || bookingId,
        first_name: (overrides.first_name as string) || booking.first_name || '',
        last_name: (overrides.last_name as string) || booking.last_name || '',
        email: (overrides.email as string) || booking.email || '',
        phone: (overrides.phone as string) || booking.phone || '',
        mobile: (overrides.mobile as string) || booking.mobile || '',
        check_in: booking.check_in || '',
        check_out: booking.check_out || '',
        notes: booking.notes || '',
        booking_status: (overrides.booking_status as string) || booking.booking_status || '',
        responsible_comm: (overrides.responsible_comm as string) || booking.responsible_comm || '',
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
        const payload = await readJsonSafely(response)
        throw new Error(getErrorMessage(payload, 'Import failed'))
      }

      try {
        const syncResponse = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/sync-all`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (!syncResponse.ok) {
          const payload = await readJsonSafely(syncResponse)
          console.error('Gmail sync failed after import:', getErrorMessage(payload, 'Gmail sync failed after import'))
        } else {
          const syncPayload = await readJsonSafely(syncResponse)
          if (syncPayload?.job_id) {
            pollGmailSyncJob(syncPayload.job_id, token, () => onImported?.())
          }
        }
      } catch (syncErr) {
        console.error('Gmail sync failed after import:', syncErr)
      }

      setBookings((current) => current.map((item) => (item.booking_id === bookingId ? { ...item, imported: true } : item)))
      setConfirmBooking(null)
      setEditFields({})
      onImported?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImportingId(null)
    }
  }

  const handleBulkImport = async () => {
    const toImport = Array.from(selectedIds)
    if (toImport.length === 0) return

    setBulkImporting(true)
    const errors: string[] = []
    let successCount = 0

    for (const bookingId of toImport) {
      try {
        setImportingId(bookingId)
        const booking = bookings.find((item) => item.booking_id === bookingId)
        if (!booking) continue

        const body = {
          booking_id: bookingId,
          name: booking.name || bookingId,
          first_name: booking.first_name || '',
          last_name: booking.last_name || '',
          email: booking.email || '',
          phone: booking.phone || '',
          mobile: booking.mobile || '',
          check_in: booking.check_in || '',
          check_out: booking.check_out || '',
          notes: booking.notes || '',
          booking_status: booking.booking_status || '',
          responsible_comm: booking.responsible_comm || '',
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
          const payload = await readJsonSafely(response)
          errors.push(`${booking.name || bookingId}: ${getErrorMessage(payload, 'Import failed')}`)
          continue
        }

        setBookings((current) =>
          current.map((item) => (item.booking_id === bookingId ? { ...item, imported: true } : item))
        )
        successCount++
      } catch (err) {
        errors.push(
          `${bookingId}: ${err instanceof Error ? err.message : 'Import failed'}`
        )
      }
    }

    try {
      const syncResponse = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/sync-all`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!syncResponse.ok) {
        const payload = await readJsonSafely(syncResponse)
        errors.push(`Gmail sync: ${getErrorMessage(payload, 'Gmail sync failed')}`)
      } else {
        const syncPayload = await readJsonSafely(syncResponse)
        if (syncPayload?.job_id) {
          pollGmailSyncJob(syncPayload.job_id, token, () => onImported?.())
        }
      }
    } catch (err) {
      errors.push(`Gmail sync: ${err instanceof Error ? err.message : 'Failed'}`)
    }

    setImportingId(null)
    setBulkImporting(false)
    setSelectedIds(new Set())

    if (errors.length > 0) {
      setError(`Imported ${successCount}/${toImport.length}. Errors: ${errors.join(' | ')}`)
    }
    onImported?.()
  }

  const getUniqueResponsiblePersons = () => {
    const persons = new Set<string>()
    bookings.forEach((b) => {
      if (b.responsible_comm) persons.add(b.responsible_comm)
    })
    return Array.from(persons).sort()
  }

  const getUniqueBookingStatuses = () => {
    const statuses = new Set<string>()
    bookings.forEach((b) => {
      if (b.booking_status) statuses.add(b.booking_status)
    })
    return Array.from(statuses).sort()
  }

  const isRecentBooking = (booking: Booking, days: number, field: 'booking_time' | 'modified_time'): boolean => {
    const value = field === 'booking_time' ? booking.booking_time : booking.modified_time
    if (!value) return false
    try {
      const referenceDate = new Date(value)
      const cutoffDate = new Date()
      cutoffDate.setDate(cutoffDate.getDate() - days)
      return referenceDate >= cutoffDate
    } catch {
      return false
    }
  }

  const isDateInRange = (dateStr: string | null, startStr: string, endStr: string): boolean => {
    if (!dateStr || (!startStr && !endStr)) return true
    if (!startStr && !endStr) return true
    try {
      const date = new Date(dateStr).toISOString().split('T')[0]
      if (startStr && date < startStr) return false
      if (endStr && date > endStr) return false
      return true
    } catch {
      return true
    }
  }

  const filteredBookings = bookings.filter((booking) => {
    const q = searchQuery.toLowerCase()
    const matchesSearch =
      booking.name?.toLowerCase().includes(q) ||
      booking.first_name?.toLowerCase().includes(q) ||
      booking.last_name?.toLowerCase().includes(q) ||
      booking.booking_id.toLowerCase().includes(q)

    const matchesResponsible =
      !filterResponsible ||
      (filterResponsible === 'unassigned' && !booking.responsible_comm) ||
      booking.responsible_comm === filterResponsible

    const matchesStatus = !filterStatus || booking.booking_status === filterStatus

    const matchesRecent = !filterRecentDays || isRecentBooking(booking, filterRecentDays, filterRecentField)

    const matchesCheckIn =
      isDateInRange(booking.check_in, filterCheckInStart, filterCheckInEnd)

    return matchesSearch && matchesResponsible && matchesStatus && matchesRecent && matchesCheckIn
  })

  const unimportedFiltered = filteredBookings.filter((b) => !b.imported)
  const allSelected = unimportedFiltered.length > 0 && unimportedFiltered.every((b) => selectedIds.has(b.booking_id))

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      const newIds = new Set(selectedIds)
      unimportedFiltered.forEach((b) => newIds.add(b.booking_id))
      setSelectedIds(newIds)
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

        {!loading && bookings.length > 0 && (
          <>
            <div className="mt-6 space-y-3">
              <input
                type="text"
                placeholder="Search by name or booking number..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-2 text-sm placeholder-gray-400 text-gray-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              />

              <div className="space-y-2">
                <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Quick filters</div>

                <div className="flex flex-wrap gap-2">
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-gray-500">Responsible:</span>
                    <button
                      type="button"
                      onClick={() => setFilterResponsible(null)}
                      className={`rounded-lg px-2 py-1 text-xs font-medium transition ${
                        filterResponsible === null
                          ? 'bg-cyan-600 text-white'
                          : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                      }`}
                    >
                      All
                    </button>
                    <button
                      type="button"
                      onClick={() => setFilterResponsible('unassigned')}
                      className={`rounded-lg px-2 py-1 text-xs font-medium transition ${
                        filterResponsible === 'unassigned'
                          ? 'bg-cyan-600 text-white'
                          : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                      }`}
                    >
                      Unassigned
                    </button>
                    {getUniqueResponsiblePersons().map((person) => (
                      <button
                        key={person}
                        type="button"
                        onClick={() => setFilterResponsible(person)}
                        className={`rounded-lg px-2 py-1 text-xs font-medium transition ${
                          filterResponsible === person
                            ? 'bg-cyan-600 text-white'
                            : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                        }`}
                      >
                        {person}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-gray-500">Status:</span>
                    <button
                      type="button"
                      onClick={() => setFilterStatus(null)}
                      className={`rounded-lg px-2 py-1 text-xs font-medium transition ${
                        filterStatus === null
                          ? 'bg-cyan-600 text-white'
                          : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                      }`}
                    >
                      All
                    </button>
                    {getUniqueBookingStatuses().map((status) => (
                      <button
                        key={status}
                        type="button"
                        onClick={() => setFilterStatus(status)}
                        className={`rounded-lg px-2 py-1 text-xs font-medium transition ${
                          filterStatus === status
                            ? 'bg-cyan-600 text-white'
                            : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                        }`}
                      >
                        {status}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-gray-500">Most recent:</span>
                    <button
                      type="button"
                      onClick={() => setFilterRecentDays(null)}
                      className={`rounded-lg px-2 py-1 text-xs font-medium transition ${
                        filterRecentDays === null
                          ? 'bg-cyan-600 text-white'
                          : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                      }`}
                    >
                      Any time
                    </button>
                    {[1, 3, 7, 10].map((days) => (
                      <button
                        key={days}
                        type="button"
                        onClick={() => setFilterRecentDays(days)}
                        className={`rounded-lg px-2 py-1 text-xs font-medium transition ${
                          filterRecentDays === days
                            ? 'bg-cyan-600 text-white'
                            : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                        }`}
                      >
                        {days}d
                      </button>
                    ))}
                    {filterRecentDays !== null && (
                      <select
                        value={filterRecentField}
                        onChange={(e) => setFilterRecentField(e.target.value as 'booking_time' | 'modified_time')}
                        className="rounded-lg border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                      >
                        <option value="booking_time">by booking date</option>
                        <option value="modified_time">by modified date</option>
                      </select>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 items-end">
                  <div className="flex items-center gap-2">
                    <div className="flex flex-col">
                      <label className="text-xs text-gray-500">Check-in from:</label>
                      <input
                        type="date"
                        value={filterCheckInStart}
                        onChange={(e) => setFilterCheckInStart(e.target.value)}
                        className="rounded-lg border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                      />
                    </div>
                    <div className="flex flex-col">
                      <label className="text-xs text-gray-500">to:</label>
                      <input
                        type="date"
                        value={filterCheckInEnd}
                        onChange={(e) => setFilterCheckInEnd(e.target.value)}
                        className="rounded-lg border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                      />
                    </div>
                    {(filterCheckInStart || filterCheckInEnd) && (
                      <button
                        type="button"
                        onClick={() => {
                          setFilterCheckInStart('')
                          setFilterCheckInEnd('')
                        }}
                        className="rounded-lg bg-gray-200 px-2 py-1 text-xs text-gray-700 hover:bg-gray-300"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between gap-3">
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={toggleSelectAll}
                    disabled={unimportedFiltered.length === 0}
                    className="rounded-lg border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-400"
                  >
                    {allSelected ? 'Deselect all' : 'Select all'}
                  </button>
                  {selectedIds.size > 0 && (
                    <span className="text-xs text-gray-500">{selectedIds.size} selected</span>
                  )}
                </div>
                {selectedIds.size > 0 && (
                  <button
                    type="button"
                    disabled={bulkImporting}
                    onClick={handleBulkImport}
                    className="rounded-lg bg-cyan-600 px-3 py-1 text-xs font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                  >
                    {bulkImporting ? 'Importing...' : `Import selected (${selectedIds.size})`}
                  </button>
                )}
              </div>
            </div>
          </>
        )}

        <div className="mt-6 max-h-[60vh] space-y-3 overflow-y-auto pr-1">
          {filteredBookings.map((booking) => (
            <div key={booking.booking_id} className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3 flex-1">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(booking.booking_id)}
                    onChange={(e) => {
                      setSelectedIds((prev) => {
                        const newSet = new Set(prev)
                        if (e.target.checked) {
                          newSet.add(booking.booking_id)
                        } else {
                          newSet.delete(booking.booking_id)
                        }
                        return newSet
                      })
                    }}
                    disabled={booking.imported}
                    className="mt-1 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                  />
                  <div className="flex-1">
                    <p className="text-base font-semibold text-gray-900">
                      {booking.name ?? <span className="italic text-gray-400">No name</span>}
                    </p>
                    <p className="mt-1 text-sm text-gray-500">
                      {booking.check_in && booking.check_out
                        ? `${booking.check_in} → ${booking.check_out}`
                        : booking.check_in || booking.check_out || 'No dates'}
                      {' · '}
                      {booking.property_name || booking.room_name || '—'}
                    </p>
                    <p className="mt-1 text-xs text-gray-400">ID: {booking.booking_id}</p>
                    <p className="mt-1 text-sm text-gray-500">{booking.booking_status || 'Unknown status'}</p>
                    {booking.responsible_comm && (
                      <p className="mt-1 text-sm text-cyan-600">Responsible: {booking.responsible_comm}</p>
                    )}
                    {(booking.referer || booking.original_referer) && (
                      <p className="mt-1 text-xs text-gray-400">
                        {booking.referer && <>Referer: {booking.referer}</>}
                        {booking.referer && booking.original_referer && ' · '}
                        {booking.original_referer && <>Original referer: {booking.original_referer}</>}
                      </p>
                    )}
                  </div>
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
                      setSelectedIds((prev) => {
                        const newSet = new Set(prev)
                        newSet.delete(booking.booking_id)
                        return newSet
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
                  onClick={() => handleImport(confirmBooking.booking_id, editFields)}
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




