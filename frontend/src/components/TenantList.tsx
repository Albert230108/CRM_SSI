import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type Tenant = {
  id: number
  booking_id: string
  name: string
  booking_status: string | null
  responsible_comm: string | null
  email: string | null
  phone: string | null
  mobile: string | null
  last_message_date: string | null
  last_message_channel: string | null
  last_message_direction: string | null
}

type TenantListProps = {
  selectedTenantId?: number
  reloadSignal?: number
}

export default function TenantList({ selectedTenantId, reloadSignal }: TenantListProps) {
  const navigate = useNavigate()
  const token = useAuthStore((state) => state.token)
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null)
  const [selectedResponsible, setSelectedResponsible] = useState<string | null>(null)
  const [sortByMessage, setSortByMessage] = useState(true)
  const [sortDesc, setSortDesc] = useState(true)
  const [livePollSignal, setLivePollSignal] = useState(0)

  useEffect(() => {
    let cancelled = false
    let lastSeenVersion: string | null = null

    const pollThreadVersion = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/communications/thread-version`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (!response.ok || cancelled) return
        const data: { latest_at: string | null } = await response.json()
        if (lastSeenVersion === null) {
          lastSeenVersion = data.latest_at
          return
        }
        if (data.latest_at !== lastSeenVersion) {
          lastSeenVersion = data.latest_at
          setLivePollSignal((current) => current + 1)
        }
      } catch {
        // Ignore transient poll failures; next interval tick will retry.
      }
    }

    const intervalId = window.setInterval(pollThreadVersion, 7000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [token])

  useEffect(() => {
    const controller = new AbortController()

    const loadTenants = async () => {
      try {
        setLoading(true)
        setError('')
        const params = new URLSearchParams()
        if (searchQuery) params.append('search', searchQuery)
        if (selectedStatus) params.append('status', selectedStatus)
        if (selectedResponsible) params.append('responsible', selectedResponsible)
        params.append('sort_by_message', sortByMessage.toString())
        params.append('sort_desc', sortDesc.toString())

        const response = await fetch(`${API_BASE_URL}/api/tenants?${params}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error('Failed to load tenants')
        }
        const data: Tenant[] = await response.json()
        setTenants(data)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load tenants')
      } finally {
        setLoading(false)
      }
    }

    loadTenants()
    return () => controller.abort()
  }, [token, reloadSignal, livePollSignal, searchQuery, selectedStatus, selectedResponsible, sortByMessage, sortDesc])

  const uniqueStatuses = useMemo(() => {
    const statuses = new Set<string>()
    tenants.forEach((t) => {
      if (t.booking_status) statuses.add(t.booking_status)
    })
    return Array.from(statuses).sort()
  }, [tenants])

  const uniqueResponsibles = useMemo(() => {
    const responsibles = new Set<string>()
    tenants.forEach((t) => {
      if (t.responsible_comm) responsibles.add(t.responsible_comm)
    })
    return Array.from(responsibles).sort()
  }, [tenants])

  const handleDelete = async (tenantId: number) => {
    if (!confirm('Delete this tenant? This cannot be undone.')) return
    const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      setTenants((current) => current.filter((tenant) => tenant.id !== tenantId))
    } else {
      alert('Failed to delete tenant')
    }
  }

  const getStatusColor = (status: string | null) => {
    if (!status) return { bg: 'bg-gray-50', border: 'border-gray-200', text: 'text-gray-700' }
    const lowerStatus = status.toLowerCase()
    if (lowerStatus.includes('confirmed')) return { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700' }
    if (lowerStatus.includes('request')) return { bg: 'bg-sky-50', border: 'border-sky-200', text: 'text-sky-700' }
    if (lowerStatus.includes('enquiry') || lowerStatus.includes('inquiry')) return { bg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-700' }
    if (lowerStatus.includes('cancelled')) return { bg: 'bg-gray-100', border: 'border-gray-300', text: 'text-gray-600' }
    return { bg: 'bg-gray-50', border: 'border-gray-200', text: 'text-gray-700' }
  }

  const getChannelIcon = (channel: string | null) => {
    if (!channel) return null
    if (channel.toLowerCase().includes('email')) return '✉️'
    if (channel.toLowerCase().includes('whatsapp')) return '💬'
    return '💬'
  }

  const getDirectionIcon = (direction: string | null) => {
    if (!direction) return null
    if (direction.toLowerCase() === 'inbound') return '⬇'
    if (direction.toLowerCase() === 'outbound') return '⬆'
    return '↔'
  }

  const formatMessageTime = (dateStr: string | null) => {
    if (!dateStr) return null
    try {
      const date = new Date(dateStr)
      const now = new Date()
      const diffMs = now.getTime() - date.getTime()
      const diffMins = Math.floor(diffMs / 60000)
      const diffHours = Math.floor(diffMs / 3600000)
      const diffDays = Math.floor(diffMs / 86400000)

      if (diffMins < 60) return `${diffMins}m ago`
      if (diffHours < 24) return `${diffHours}h ago`
      if (diffDays < 7) return `${diffDays}d ago`
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    } catch {
      return null
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col space-y-3">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Tenants</h2>
      </div>

      <div className="space-y-2">
        <input
          type="text"
          placeholder="Search by name, ID, email..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-gray-200 px-3 py-1.5 text-sm placeholder-gray-400 outline-none focus:border-cyan-300 focus:ring-1 focus:ring-cyan-200"
        />

        <div className="flex gap-2">
          <select
            value={selectedStatus || ''}
            onChange={(e) => setSelectedStatus(e.target.value || null)}
            className="flex-1 rounded-lg border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-cyan-300 focus:ring-1 focus:ring-cyan-200"
          >
            <option value="">All Statuses</option>
            {uniqueStatuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>

          <button
            onClick={() => setSortDesc(!sortDesc)}
            className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs font-medium text-gray-600 transition hover:bg-gray-50"
            title={sortDesc ? 'Sort ascending' : 'Sort descending'}
          >
            {sortDesc ? '↓' : '↑'}
          </button>
        </div>

        <select
          value={selectedResponsible || ''}
          onChange={(e) => setSelectedResponsible(e.target.value || null)}
          className="w-full rounded-lg border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-cyan-300 focus:ring-1 focus:ring-cyan-200"
        >
          <option value="">All Responsible</option>
          <option value="unassigned">Unassigned</option>
          {uniqueResponsibles.map((responsible) => (
            <option key={responsible} value={responsible}>
              {responsible}
            </option>
          ))}
        </select>
      </div>

      {loading ? <p className="text-xs text-gray-500">Loading tenants...</p> : null}
      {error ? <p className="text-xs text-rose-400">{error}</p> : null}

      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-2 [scrollbar-width:thin] [scrollbar-color:rgba(34,197,94,0.35)_transparent]">
        {tenants.length === 0 ? (
          <p className="text-xs text-gray-400">No tenants found</p>
        ) : (
          tenants.map((tenant) => {
            const active = selectedTenantId === tenant.id
            const colors = getStatusColor(tenant.booking_status)
            const contact = [tenant.email, tenant.phone, tenant.mobile].filter(Boolean).join(' · ') || 'No contact'
            const msgTime = formatMessageTime(tenant.last_message_date)
            const channelIcon = getChannelIcon(tenant.last_message_channel)
            const directionIcon = getDirectionIcon(tenant.last_message_direction)

            return (
              <button
                key={tenant.id}
                onClick={() => navigate(`/dashboard/tenant/${tenant.id}`)}
                className={[
                  'w-full rounded-xl border p-2.5 text-left transition',
                  active ? `border-cyan-500 ${colors.bg} shadow-sm` : `${colors.border} ${colors.bg} hover:opacity-75`,
                ].join(' ')}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className={`text-sm font-semibold ${colors.text}`}>{tenant.name}</p>
                    <p className="truncate text-xs text-gray-600 mt-0.5">{contact}</p>
                    {msgTime && (
                      <p className="text-[10px] text-gray-500 mt-1 flex items-center gap-1">
                        <span>{msgTime}</span>
                        {channelIcon && <span>{channelIcon}</span>}
                        {directionIcon && <span>{directionIcon}</span>}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDelete(tenant.id)
                    }}
                    className="shrink-0 rounded-lg p-1 text-rose-400 transition hover:bg-rose-50 hover:text-rose-600"
                    aria-label={`Delete tenant ${tenant.id}`}
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
                      <path d="M3 6h18" />
                      <path d="M8 6V4h8v2" />
                      <path d="M19 6l-1 14H6L5 6" />
                      <path d="M10 11v6" />
                      <path d="M14 11v6" />
                    </svg>
                  </button>
                </div>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
