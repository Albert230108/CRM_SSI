import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useToast } from '../lib/useToast'
import ToastHost from '../components/Toast'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type ActionItem = {
  id: number
  tenant_id: number
  tenant_name: string | null
  title: string
  description: string | null
  due_date: string | null
  status: 'open' | 'done' | 'dismissed'
  source: 'manual' | 'ai'
}

const STATUS_FILTERS: Array<{ id: string; label: string }> = [
  { id: 'open', label: 'Open' },
  { id: 'done', label: 'Done' },
  { id: 'dismissed', label: 'Dismissed' },
  { id: '', label: 'All' },
]

export default function Actions() {
  const token = useAuthStore((state) => state.token)
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined
  const { toast, showError, dismiss } = useToast()

  const [statusFilter, setStatusFilter] = useState('open')
  const [items, setItems] = useState<ActionItem[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const params = statusFilter ? `?status=${statusFilter}` : ''
      const response = await fetch(`${API_BASE_URL}/api/action-items${params}`, { headers: authHeaders })
      if (!response.ok) throw new Error()
      setItems(await response.json())
    } catch {
      showError('Failed to load action items')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  const transition = async (id: number, action: 'complete' | 'dismiss' | 'reopen') => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/action-items/${id}/${action}`, { method: 'POST', headers: authHeaders })
      if (!response.ok) throw new Error()
      await load()
    } catch {
      showError('Failed to update action item')
    }
  }

  return (
    <>
      <main className="mx-auto max-w-5xl px-6 py-4">
        <h1 className="text-2xl font-semibold text-gray-900">Actions</h1>
        <p className="mt-1 text-sm text-gray-500">Checklist items across every tenant, added manually or suggested by AI.</p>

        <div className="mt-3 flex gap-1.5">
          {STATUS_FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              onClick={() => setStatusFilter(filter.id)}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                statusFilter === filter.id ? 'bg-cyan-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-100'
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>

        <div className="mt-3 space-y-2">
          {loading ? (
            <p className="text-sm text-gray-500">Loading...</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-gray-400">Nothing here.</p>
          ) : (
            items.map((item) => (
              <div key={item.id} className="rounded-xl border border-gray-200 bg-white p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link to={`/dashboard/tenant/${item.tenant_id}`} className="text-xs font-semibold uppercase tracking-wide text-cyan-700 hover:underline">
                      {item.tenant_name ?? `Tenant #${item.tenant_id}`}
                    </Link>
                    <p className={`mt-0.5 text-sm ${item.status === 'done' ? 'text-gray-400 line-through' : 'text-gray-900'}`}>{item.title}</p>
                    {item.description ? <p className="mt-0.5 text-xs text-gray-500">{item.description}</p> : null}
                    <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
                      <span className={`rounded-full px-2 py-0.5 ${item.source === 'ai' ? 'bg-cyan-50 text-cyan-700' : 'bg-gray-100 text-gray-600'}`}>
                        {item.source === 'ai' ? 'AI' : 'Manual'}
                      </span>
                      {item.due_date ? <span>Due {item.due_date}</span> : null}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {item.status === 'open' ? (
                      <>
                        <button type="button" onClick={() => transition(item.id, 'complete')} className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
                          Done
                        </button>
                        <button type="button" onClick={() => transition(item.id, 'dismiss')} className="rounded-full border border-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-500">
                          Dismiss
                        </button>
                      </>
                    ) : (
                      <button type="button" onClick={() => transition(item.id, 'reopen')} className="rounded-full border border-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-500">
                        Reopen
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </main>
      <ToastHost toast={toast} onDismiss={dismiss} />
    </>
  )
}
