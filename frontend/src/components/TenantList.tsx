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
        <p className="text-xs uppercase tracking-[0.35em] text-cyan-400">Tenants</p>
        <h2 className="mt-1 text-xl font-semibold text-white">Booking groups</h2>
      </div>

      {loading ? <p className="text-sm text-slate-400">Loading tenants...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <div className="space-y-4">
        {statusOrder.map((status) => (
          <section key={status} className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-slate-200">{status}</h3>
              <span className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-400">{groupedTenants[status].length}</span>
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
                        ? 'border-cyan-500 bg-cyan-500/10 shadow-lg shadow-cyan-950/20'
                        : 'border-slate-800 bg-slate-900 hover:border-slate-700 hover:bg-slate-800/70',
                    ].join(' ')}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-base font-semibold text-white">{tenant.name}</p>
                        <p className="mt-1 text-sm text-slate-400">Tenant ID {tenant.id}</p>
                      </div>
                      <span className="rounded-full bg-slate-800 px-2 py-1 text-xs text-slate-300">#{tenant.id}</span>
                    </div>
                    <div className="mt-3 rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">Responsible comm</p>
                      <p className="mt-1 text-sm font-medium text-cyan-300">{tenant.responsible_comm || 'Unassigned'}</p>
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
