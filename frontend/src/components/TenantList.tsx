import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { formatRelativeTime, getChannelIcon } from '../lib/timeFormat'
import { useAuthStore } from '../store/authStore'
import StatusFilterDropdown from './StatusFilterDropdown'
import TenantContextMenu from './TenantContextMenu'
import TenantAiTemplatesModal from './TenantAiTemplatesModal'

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

type ThreadVersion = {
  latest_at: string | null
  tenant_id?: number | null
  tenant_name?: string | null
  channel?: string | null
  direction?: string | null
}

type TenantListProps = {
  selectedTenantId?: number
  reloadSignal?: number
  onNewMessage?: (info: { tenantName: string; channel: string; direction: string }) => void
}

export default function TenantList({ selectedTenantId, reloadSignal, onNewMessage }: TenantListProps) {
  const navigate = useNavigate()
  const token = useAuthStore((state) => state.token)
  const [searchParams, setSearchParams] = useSearchParams()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [statusOptions, setStatusOptions] = useState<string[]>([])
  const [statusOptionsLoaded, setStatusOptionsLoaded] = useState(false)
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>([])
  const [statusesResolved, setStatusesResolved] = useState(false)
  const statusesInitializedRef = useRef(false)
  const [selectedResponsible, setSelectedResponsible] = useState<string | null>(null)
  const [selectedDirection, setSelectedDirection] = useState<string | null>(null)
  const [sortByMessage, setSortByMessage] = useState(true)
  const [sortDesc, setSortDesc] = useState(true)
  const [livePollSignal, setLivePollSignal] = useState(0)
  const onNewMessageRef = useRef(onNewMessage)
  const [contextMenu, setContextMenu] = useState<{ tenantId: number; tenantName: string; x: number; y: number } | null>(null)
  const [aiTemplatesTenant, setAiTemplatesTenant] = useState<{ id: number; name: string } | null>(null)

  useEffect(() => {
    onNewMessageRef.current = onNewMessage
  }, [onNewMessage])

  useEffect(() => {
    let cancelled = false
    const loadStatusOptions = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/tenants/statuses`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (!cancelled && response.ok) {
          const data: string[] = await response.json()
          setStatusOptions(data)
        }
      } catch {
        // Ignore; the status filter dropdown will just stay empty until the next refresh.
      } finally {
        if (!cancelled) setStatusOptionsLoaded(true)
      }
    }
    loadStatusOptions()
    return () => {
      cancelled = true
    }
  }, [token, reloadSignal, livePollSignal])

  useEffect(() => {
    if (statusesInitializedRef.current) return

    if (searchParams.has('statuses')) {
      const raw = searchParams.get('statuses') ?? ''
      const parsed = raw
        .split(',')
        .map((value) => decodeURIComponent(value))
        .filter(Boolean)
      setSelectedStatuses(parsed)
      statusesInitializedRef.current = true
      setStatusesResolved(true)
      return
    }

    // Wait until we know which statuses actually exist before picking the "all selected" default.
    if (!statusOptionsLoaded) return

    let cancelled = false
    const loadSavedPreference = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/users/me/tenant-status-filter`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (cancelled) return
        if (response.ok) {
          const data: { statuses: string[] | null } = await response.json()
          setSelectedStatuses(data.statuses ?? statusOptions)
        } else {
          setSelectedStatuses(statusOptions)
        }
      } catch {
        if (!cancelled) setSelectedStatuses(statusOptions)
      } finally {
        if (!cancelled) {
          statusesInitializedRef.current = true
          setStatusesResolved(true)
        }
      }
    }

    loadSavedPreference()
    return () => {
      cancelled = true
    }
  }, [searchParams, statusOptionsLoaded, statusOptions, token])

  const handleStatusesChange = (next: string[]) => {
    setSelectedStatuses(next)

    const params = new URLSearchParams(searchParams)
    params.set('statuses', next.map((value) => encodeURIComponent(value)).join(','))
    setSearchParams(params, { replace: true })

    fetch(`${API_BASE_URL}/api/users/me/tenant-status-filter`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ statuses: next }),
    }).catch(() => {
      // Best-effort save; the URL still reflects the current session's selection.
    })
  }

  useEffect(() => {
    let cancelled = false
    let lastSeenVersion: string | null = null

    const pollThreadVersion = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/communications/thread-version`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (!response.ok || cancelled) return
        const data: ThreadVersion = await response.json()
        if (lastSeenVersion === null) {
          lastSeenVersion = data.latest_at
          return
        }
        if (data.latest_at !== lastSeenVersion) {
          lastSeenVersion = data.latest_at
          setLivePollSignal((current) => current + 1)
          if (data.tenant_id != null && data.channel && data.direction === 'inbound' && data.tenant_name) {
            onNewMessageRef.current?.({ tenantName: data.tenant_name, channel: data.channel, direction: data.direction })
          }
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
    if (!statusesResolved) return
    const controller = new AbortController()

    const loadTenants = async () => {
      try {
        setLoading(true)
        setError('')
        const params = new URLSearchParams()
        if (searchQuery) params.append('search', searchQuery)
        params.append('status_filter', 'true')
        selectedStatuses.forEach((status) => params.append('status', status))
        if (selectedResponsible) params.append('responsible', selectedResponsible)
        if (selectedDirection) params.append('last_message_direction', selectedDirection)
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
  }, [token, reloadSignal, livePollSignal, searchQuery, selectedStatuses, statusesResolved, selectedResponsible, selectedDirection, sortByMessage, sortDesc])

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

  const getDirectionIcon = (direction: string | null) => {
    if (!direction) return null
    if (direction.toLowerCase() === 'inbound') return '⬇'
    if (direction.toLowerCase() === 'outbound') return '⬆'
    return '↔'
  }

  return (
    <div className="flex h-full min-h-0 flex-col space-y-2">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Tenants</h2>
      </div>

      <div className="space-y-1.5">
        <div className="relative">
          <input
            type="text"
            placeholder="Search by name, ID, email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-gray-200 px-3 py-1.5 pr-8 text-sm placeholder-gray-400 outline-none focus:border-cyan-300 focus:ring-1 focus:ring-cyan-200"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-gray-400 hover:text-gray-600"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                <path fillRule="evenodd" d="M10 8.586 5.707 4.293a1 1 0 0 0-1.414 1.414L8.586 10l-4.293 4.293a1 1 0 1 0 1.414 1.414L10 11.414l4.293 4.293a1 1 0 0 0 1.414-1.414L11.414 10l4.293-4.293a1 1 0 0 0-1.414-1.414L10 8.586Z" clipRule="evenodd" />
              </svg>
            </button>
          )}
        </div>

        <div className="flex gap-1.5">
          <StatusFilterDropdown options={statusOptions} selected={selectedStatuses} onChange={handleStatusesChange} />

          <select
            value={selectedResponsible || ''}
            onChange={(e) => setSelectedResponsible(e.target.value || null)}
            className="min-w-0 flex-1 rounded-lg border border-gray-200 px-2 py-1 text-xs outline-none focus:border-cyan-300 focus:ring-1 focus:ring-cyan-200"
          >
            <option value="">All Responsible</option>
            <option value="unassigned">Unassigned</option>
            {uniqueResponsibles.map((responsible) => (
              <option key={responsible} value={responsible}>
                {responsible}
              </option>
            ))}
          </select>

          <button
            onClick={() => setSortDesc(!sortDesc)}
            className="shrink-0 rounded-lg border border-gray-200 px-2 py-1 text-xs font-medium text-gray-600 transition hover:bg-gray-50"
            title={sortDesc ? 'Sort ascending' : 'Sort descending'}
          >
            {sortDesc ? '↓' : '↑'}
          </button>
        </div>

        <select
          value={selectedDirection || ''}
          onChange={(e) => setSelectedDirection(e.target.value || null)}
          className="w-full rounded-lg border border-gray-200 px-2 py-1 text-xs outline-none focus:border-cyan-300 focus:ring-1 focus:ring-cyan-200"
        >
          <option value="">All Last Messages</option>
          <option value="inbound">Last Message Inbound ⬇</option>
          <option value="outbound">Last Message Outbound ⬆</option>
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
            const msgTime = formatRelativeTime(tenant.last_message_date)
            const channelIcon = getChannelIcon(tenant.last_message_channel)
            const directionIcon = getDirectionIcon(tenant.last_message_direction)

            return (
              <button
                key={tenant.id}
                onClick={() => navigate(`/dashboard/tenant/${tenant.id}`)}
                onContextMenu={(e) => {
                  e.preventDefault()
                  setContextMenu({ tenantId: tenant.id, tenantName: tenant.name, x: e.clientX, y: e.clientY })
                }}
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

      {contextMenu ? (
        <TenantContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onEditAiTemplates={() => setAiTemplatesTenant({ id: contextMenu.tenantId, name: contextMenu.tenantName })}
          onClose={() => setContextMenu(null)}
        />
      ) : null}

      {aiTemplatesTenant ? (
        <TenantAiTemplatesModal
          tenantId={aiTemplatesTenant.id}
          tenantName={aiTemplatesTenant.name}
          onClose={() => setAiTemplatesTenant(null)}
        />
      ) : null}
    </div>
  )
}
