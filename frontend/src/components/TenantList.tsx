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

  useEffect(() => {
    const controller = new AbortController()

    const loadTenants = async () => {
      try {
        setLoading(true)
        setError('')
        const response = await fetch(`${API_BASE_URL}/api/tenants`, {
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
  }, [token, reloadSignal])

  const groupedTenants = useMemo(() => {
    return tenants.reduce<Record<string, Tenant[]>>((groups, tenant) => {
      const key = tenant.booking_status?.trim() || 'Unknown'
      if (!groups[key]) groups[key] = []
      groups[key].push(tenant)
      return groups
    }, {})
  }, [tenants])

  const statusOrder = useMemo(() => Object.keys(groupedTenants).sort((left, right) => left.localeCompare(right)), [groupedTenants])

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

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">Tenants</h2>
      </div>

      {loading ? <p className="text-sm text-gray-500">Loading tenants...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-2">
        {statusOrder.map((status) => (
          <section key={status} className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-700">{status}</h3>
              <span className="rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-500">{groupedTenants[status].length}</span>
            </div>

            <div className="space-y-2">
              {groupedTenants[status].map((tenant) => {
                const active = selectedTenantId === tenant.id
                return (
                  <div
                    key={tenant.id}
                    className={[
                      'w-full rounded-2xl border p-4 text-left transition',
                      active
                        ? 'border-cyan-500 bg-cyan-50 shadow-sm'
                        : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50',
                    ].join(' ')}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <button type="button" onClick={() => navigate(`/dashboard/tenant/${tenant.id}`)} className="min-w-0 flex-1 text-left">
                        <p className="text-base font-semibold text-gray-900">{tenant.name}</p>
                        <p className="mt-1 text-sm text-gray-500">Booking {tenant.booking_id}</p>
                      </button>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleDelete(tenant.id)}
                          className="rounded-lg p-2 text-rose-500 transition hover:bg-rose-50 hover:text-rose-700"
                          aria-label={`Delete tenant ${tenant.id}`}
                        >
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                            <path d="M3 6h18" />
                            <path d="M8 6V4h8v2" />
                            <path d="M19 6l-1 14H6L5 6" />
                            <path d="M10 11v6" />
                            <path d="M14 11v6" />
                          </svg>
                        </button>
                      </div>
                    </div>
                    <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-gray-500">Contact</p>
                      <p className="mt-1 text-sm font-medium text-cyan-700">{tenant.responsible_comm || 'Unassigned'}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
