import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, apiGet, decodeTokenClaims, getToken } from '../lib/apiClient'
import type { Beds24Booking, TenantContext } from '../lib/types'

export default function BookingSearchPage() {
  const navigate = useNavigate()
  const [sessionBookingId, setSessionBookingId] = useState<string | null>(null)
  const [tenantContext, setTenantContext] = useState<TenantContext | null>(null)
  const [searchValue, setSearchValue] = useState('')
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const token = getToken()
    if (!token) {
      setError('No access token found. Open the Quotation Manager from a tenant in the CRM.')
      return
    }
    const claims = decodeTokenClaims(token)
    if (!claims) {
      setError('The access token could not be read. Please reopen the Quotation Manager from the CRM.')
      return
    }
    setSessionBookingId(claims.booking_id)

    if (claims.tenant_id) {
      apiGet<TenantContext>(`/api/booking/tenant-context/${claims.tenant_id}`)
        .then(setTenantContext)
        .catch((err: unknown) => {
          const message = err instanceof ApiError ? err.message : 'Failed to load tenant context'
          setError(message)
        })
    }
  }, [])

  const handleSearch = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!searchValue.trim()) return
    setSearching(true)
    setError(null)
    try {
      const booking = await apiGet<Beds24Booking>(`/api/booking/${encodeURIComponent(searchValue.trim())}`)
      navigate(`/quotation/${encodeURIComponent(booking.id)}`)
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Booking not found'
      setError(message)
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Quotation Manager</h1>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => navigate('/new')}
            className="rounded-lg border border-cyan-600 px-3 py-1.5 text-sm font-medium text-cyan-700 hover:bg-cyan-50"
          >
            + New quotation
          </button>
          <button
            type="button"
            onClick={() => navigate('/settings')}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Settings
          </button>
        </div>
      </div>

      {error ? (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p>
      ) : null}

      {tenantContext ? (
        <div className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Current tenant</p>
          <p className="mt-1 text-lg font-medium text-gray-900">{tenantContext.name}</p>
          <p className="text-sm text-gray-500">
            {tenantContext.room_name ?? 'Unknown room'} &middot; {tenantContext.property_name ?? 'Unknown property'}
          </p>
          <p className="text-sm text-gray-500">
            {tenantContext.check_in ?? '—'} to {tenantContext.check_out ?? '—'}
          </p>
          <button
            type="button"
            onClick={() => navigate(`/quotation/${encodeURIComponent(tenantContext.booking_id)}`)}
            className="mt-3 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-700"
          >
            Open quotation for booking {tenantContext.booking_id}
          </button>
        </div>
      ) : sessionBookingId ? (
        <div className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <button
            type="button"
            onClick={() => navigate(`/quotation/${encodeURIComponent(sessionBookingId)}`)}
            className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-700"
          >
            Open quotation for booking {sessionBookingId}
          </button>
        </div>
      ) : null}

      <form onSubmit={handleSearch} className="mt-6 flex gap-2">
        <input
          type="text"
          value={searchValue}
          onChange={(event) => setSearchValue(event.target.value)}
          placeholder="Search a different booking ID"
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-cyan-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={searching}
          className="rounded-lg bg-gray-800 px-4 py-2 text-sm font-medium text-white hover:bg-gray-900 disabled:opacity-50"
        >
          {searching ? 'Searching...' : 'Search'}
        </button>
      </form>
    </div>
  )
}
