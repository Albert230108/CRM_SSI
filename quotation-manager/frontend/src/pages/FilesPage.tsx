import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, apiGet, getToken } from '../lib/apiClient'

type FileEntry = {
  name: string
  kind: 'file' | 'directory'
  size: number | null
  relative_path: string
}

const API_BASE_URL = import.meta.env.VITE_QUOTATION_API_BASE_URL ?? ''

function formatBytes(bytes: number | null) {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`
}

export default function FilesPage() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [bookingId, setBookingId] = useState('')
  const [year, setYear] = useState('')
  const [tenantName, setTenantName] = useState('')
  const [room, setRoom] = useState('')
  const [items, setItems] = useState<FileEntry[]>([])
  const [searched, setSearched] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runSearch = async (event?: React.FormEvent) => {
    event?.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (q.trim()) params.set('q', q.trim())
      if (bookingId.trim()) params.set('booking_id', bookingId.trim())
      if (year.trim()) params.set('year', year.trim())
      if (tenantName.trim()) params.set('tenant_name', tenantName.trim())
      if (room.trim()) params.set('room', room.trim())
      const query = params.toString()
      const result = await apiGet<{ items: FileEntry[] }>(`/api/quotation/tenant-files/search${query ? `?${query}` : ''}`)
      setItems(result.items)
      setSearched(true)
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Failed to search tenant files'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const openFile = async (item: FileEntry) => {
    setError(null)
    try {
      const token = getToken()
      const response = await fetch(
        `${API_BASE_URL}/api/quotation/tenant-files/download?path=${encodeURIComponent(item.relative_path)}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
      )
      if (!response.ok) throw new Error('Failed to download file')
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener,noreferrer')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to open file')
    }
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Files</h1>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Back to search
        </button>
      </div>
      <p className="mt-1 text-sm text-gray-500">Browse and search quotations across every tenant's server folder.</p>

      <form onSubmit={runSearch} className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <input
          type="text"
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder="Search filename/folder"
          className="col-span-2 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-cyan-500 focus:outline-none sm:col-span-1"
        />
        <input
          type="text"
          value={bookingId}
          onChange={(event) => setBookingId(event.target.value)}
          placeholder="Booking ID"
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-cyan-500 focus:outline-none"
        />
        <input
          type="text"
          value={tenantName}
          onChange={(event) => setTenantName(event.target.value)}
          placeholder="Tenant name"
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-cyan-500 focus:outline-none"
        />
        <input
          type="text"
          value={room}
          onChange={(event) => setRoom(event.target.value)}
          placeholder="Room"
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-cyan-500 focus:outline-none"
        />
        <input
          type="number"
          value={year}
          onChange={(event) => setYear(event.target.value)}
          placeholder="Year"
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-cyan-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-gray-800 px-4 py-2 text-sm font-medium text-white hover:bg-gray-900 disabled:opacity-50"
        >
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {error ? (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p>
      ) : null}

      <ul className="mt-4 space-y-1.5">
        {searched && !loading && items.length === 0 ? (
          <li className="text-sm text-gray-500">No files matched.</li>
        ) : null}
        {items.map((item) => (
          <li
            key={item.relative_path}
            className="flex items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white p-3 shadow-sm"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-gray-900">{item.name}</p>
              <p className="mt-0.5 text-xs uppercase tracking-[0.15em] text-gray-500">
                {item.relative_path.split('/').slice(0, -1).join(' / ')}
                {item.size != null ? ` · ${formatBytes(item.size)}` : ''}
              </p>
            </div>
            <button
              type="button"
              onClick={() => openFile(item)}
              className="shrink-0 rounded-lg border border-cyan-600 px-3 py-1.5 text-sm font-medium text-cyan-700 hover:bg-cyan-50"
            >
              Open
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
