import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type Tenant = {
  id: number
  name: string
  booking_status: string | null
  responsible_comm: string | null
}

type TenantListProps = {
  selectedTenantId?: number
}

export default function TenantList({ selectedTenantId }: TenantListProps) {
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
  }, [token])

  const groupedTenants = useMemo(() => {
    return tenants.reduce<Record<string, Tenant[]>>((groups, tenant) => {
      const key = tenant.booking_status?.trim() || 'Unknown'
      if (!groups[key]) groups[key] = []
      groups[key].push(tenant)
      return groups
    }, {})
  }, [tenants])

  const statusOrder = useMemo(() => Object.keys(groupedTenants).sort((left, right) => left.localeCompare(right)), [groupedTenants])

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs uppercase tracking-[0.35em] text-cyan-600">Tenants</p>
        <h2 className="mt-1 text-xl font-semibold text-gray-900">Booking groups</h2>
      </div>

      {loading ? <p className="text-sm text-gray-500">Loading tenants...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <div className="space-y-4">
        {statusOrder.map((status) => (
          <section key={status} className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-700">{status}</h3>
              <span className="rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-500">{groupedTenants[status].length}</span>
            </div>

            <div className="space-y-2">
              {groupedTenants[status].map((tenant) => {
                const active = selectedTenantId === tenant.id
                return (
                  <button
                    key={tenant.id}
                    type="button"
                    onClick={() => navigate(`/dashboard/tenant/${tenant.id}`)}
                    className={[
                      'w-full rounded-2xl border p-4 text-left transition',
                      active
                        ? 'border-cyan-500 bg-cyan-50 shadow-sm'
                        : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50',
                    ].join(' ')}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-base font-semibold text-gray-900">{tenant.name}</p>
                        <p className="mt-1 text-sm text-gray-500">Tenant ID {tenant.id}</p>
                      </div>
                      <span className="rounded-full bg-gray-100 px-2 py-1 text-xs text-gray-600">#{tenant.id}</span>
                    </div>
                    <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-gray-500">Responsible comm</p>
                      <p className="mt-1 text-sm font-medium text-cyan-700">{tenant.responsible_comm || 'Unassigned'}</p>
                    </div>
                  </button>
                )
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
