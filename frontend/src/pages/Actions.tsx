import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useToast } from '../lib/useToast'
import ToastHost from '../components/Toast'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type Priority = 'p1' | 'p2' | 'p3' | 'p4'

type ActionItem = {
  id: number
  tenant_id: number
  tenant_name: string | null
  title: string
  description: string | null
  due_date: string | null
  status: 'open' | 'done' | 'dismissed'
  source: 'manual' | 'ai'
  tag_name: string | null
  tag_color: string | null
  priority: Priority | null
}

const STATUS_FILTERS: Array<{ id: string; label: string }> = [
  { id: 'open', label: 'Open' },
  { id: 'done', label: 'Done' },
  { id: 'dismissed', label: 'Dismissed' },
  { id: '', label: 'All' },
]

const PRIORITY_STYLE: Record<Priority, string> = {
  p1: 'bg-rose-50 text-rose-700',
  p2: 'bg-orange-50 text-orange-700',
  p3: 'bg-amber-50 text-amber-700',
  p4: 'bg-blue-50 text-blue-700',
}

const PRIORITY_LABEL: Record<Priority, string> = { p1: 'P1', p2: 'P2', p3: 'P3', p4: 'P4' }

const PRIORITY_FILTERS: Array<{ id: Priority | ''; label: string }> = [
  { id: '', label: 'Any priority' },
  { id: 'p1', label: 'P1' },
  { id: 'p2', label: 'P2' },
  { id: 'p3', label: 'P3' },
  { id: 'p4', label: 'P4' },
]

type ActionItemSuggestionSnapshot = {
  title: string
  description: string | null
  due_date: string | null
  priority: Priority | null
  tag_name: string | null
  tag_color: string | null
  status: string
}

type ActionItemSuggestion = {
  id: number
  kind: 'action_item_modify' | 'action_item_delete'
  tenant_id: number
  tenant_name: string | null
  action_item_id: number
  current: ActionItemSuggestionSnapshot
  proposed: Record<string, unknown>
  reasoning: string | null
  created_at: string
}

function DiffRow({ label, oldValue, newValue }: { label: string; oldValue: string; newValue: string }) {
  return (
    <div className="flex items-baseline gap-2 text-sm">
      <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</span>
      <span className="text-gray-400 line-through">{oldValue || '—'}</span>
      <span className="text-gray-400">&rarr;</span>
      <span className="font-medium text-gray-900">{newValue || '—'}</span>
    </div>
  )
}

export default function Actions() {
  const token = useAuthStore((state) => state.token)
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined
  const { toast, showError, dismiss } = useToast()

  const [statusFilter, setStatusFilter] = useState('open')
  const [priorityFilter, setPriorityFilter] = useState<Priority | ''>('')
  const [items, setItems] = useState<ActionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [suggestions, setSuggestions] = useState<ActionItemSuggestion[]>([])
  const [loadingSuggestions, setLoadingSuggestions] = useState(true)

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

  const loadSuggestions = async () => {
    setLoadingSuggestions(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/action-items/pending-suggestions`, { headers: authHeaders })
      if (!response.ok) throw new Error()
      setSuggestions(await response.json())
    } catch {
      showError('Failed to load pending action changes')
    } finally {
      setLoadingSuggestions(false)
    }
  }

  useEffect(() => {
    loadSuggestions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const visibleItems = priorityFilter ? items.filter((item) => item.priority === priorityFilter) : items

  const transition = async (id: number, action: 'complete' | 'dismiss' | 'reopen') => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/action-items/${id}/${action}`, { method: 'POST', headers: authHeaders })
      if (!response.ok) throw new Error()
      await load()
    } catch {
      showError('Failed to update action item')
    }
  }

  const reviewSuggestion = async (suggestion: ActionItemSuggestion, action: 'approve' | 'reject') => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/memory-suggestions/${suggestion.id}/${action}`, { method: 'POST', headers: authHeaders })
      const data = await response.json().catch(() => null)
      if (!response.ok) throw new Error()
      if (action === 'approve' && data?.applied === false) {
        showError(data?.message ?? 'Could not apply that change')
      }
      await Promise.all([loadSuggestions(), load()])
    } catch {
      showError(`Failed to ${action} that change`)
    }
  }

  return (
    <>
      <main className="mx-auto max-w-5xl px-6 py-4">
        <h1 className="text-2xl font-semibold text-gray-900">Actions</h1>
        <p className="mt-1 text-sm text-gray-500">Checklist items across every tenant, added manually or suggested by AI.</p>

        {!loadingSuggestions && suggestions.length > 0 ? (
          <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 p-3.5">
            <h2 className="text-sm font-semibold text-amber-900">Pending Action Changes</h2>
            <p className="mt-0.5 text-xs text-amber-700">
              The action-writer AI wants to change or remove these existing items. Nothing applies until you approve it.
            </p>
            <div className="mt-2 space-y-2">
              {suggestions.map((suggestion) => (
                <div key={suggestion.id} className="rounded-xl border border-amber-200 bg-white p-2.5 text-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Link to={`/dashboard/tenant/${suggestion.tenant_id}`} className="text-xs font-semibold uppercase tracking-wide text-cyan-700 hover:underline">
                          {suggestion.tenant_name ?? `Tenant #${suggestion.tenant_id}`}
                        </Link>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${suggestion.kind === 'action_item_delete' ? 'bg-rose-50 text-rose-700' : 'bg-cyan-50 text-cyan-700'}`}>
                          {suggestion.kind === 'action_item_delete' ? 'Delete' : 'Modify'}
                        </span>
                      </div>

                      {suggestion.kind === 'action_item_delete' ? (
                        <div className="mt-1.5">
                          <p className="text-gray-900 line-through">{suggestion.current.title}</p>
                          <p className="mt-0.5 text-xs text-rose-600">This item will be deleted.</p>
                        </div>
                      ) : (
                        <div className="mt-1.5 space-y-0.5">
                          {'title' in suggestion.proposed ? (
                            <DiffRow label="Title" oldValue={suggestion.current.title} newValue={String(suggestion.proposed.title ?? '')} />
                          ) : (
                            <p className="text-gray-900">{suggestion.current.title}</p>
                          )}
                          {'due_date' in suggestion.proposed ? (
                            <DiffRow label="Due" oldValue={suggestion.current.due_date ?? ''} newValue={String(suggestion.proposed.due_date ?? '')} />
                          ) : null}
                          {'priority' in suggestion.proposed ? (
                            <DiffRow label="Priority" oldValue={suggestion.current.priority ?? ''} newValue={String(suggestion.proposed.priority ?? '')} />
                          ) : null}
                          {'tag_id' in suggestion.proposed ? (
                            <DiffRow label="Tag" oldValue={suggestion.current.tag_name ?? ''} newValue={String(suggestion.proposed.tag_name ?? '')} />
                          ) : null}
                        </div>
                      )}

                      {suggestion.reasoning ? <p className="mt-1.5 text-xs italic text-gray-500">&ldquo;{suggestion.reasoning}&rdquo;</p> : null}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <button
                        type="button"
                        onClick={() => reviewSuggestion(suggestion, 'approve')}
                        className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700"
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => reviewSuggestion(suggestion, 'reject')}
                        className="rounded-full border border-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-500"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

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

        <div className="mt-2 flex gap-1.5">
          {PRIORITY_FILTERS.map((filter) => (
            <button
              key={filter.id || 'any'}
              type="button"
              onClick={() => setPriorityFilter(filter.id)}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                priorityFilter === filter.id ? 'bg-gray-800 text-white' : 'border border-gray-200 text-gray-600 hover:bg-gray-100'
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>

        <div className="mt-3 space-y-2">
          {loading ? (
            <p className="text-sm text-gray-500">Loading...</p>
          ) : visibleItems.length === 0 ? (
            <p className="text-sm text-gray-400">Nothing here.</p>
          ) : (
            visibleItems.map((item) => (
              <div key={item.id} className="rounded-xl border border-gray-200 bg-white p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link to={`/dashboard/tenant/${item.tenant_id}`} className="text-xs font-semibold uppercase tracking-wide text-cyan-700 hover:underline">
                      {item.tenant_name ?? `Tenant #${item.tenant_id}`}
                    </Link>
                    <p className={`mt-0.5 text-sm ${item.status === 'done' ? 'text-gray-400 line-through' : 'text-gray-900'}`}>{item.title}</p>
                    {item.description ? <p className="mt-0.5 text-xs text-gray-500">{item.description}</p> : null}
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-400">
                      <span className={`rounded-full px-2 py-0.5 ${item.source === 'ai' ? 'bg-cyan-50 text-cyan-700' : 'bg-gray-100 text-gray-600'}`}>
                        {item.source === 'ai' ? 'AI' : 'Manual'}
                      </span>
                      {item.priority ? <span className={`rounded-full px-2 py-0.5 font-semibold ${PRIORITY_STYLE[item.priority]}`}>{PRIORITY_LABEL[item.priority]}</span> : null}
                      {item.tag_name ? (
                        <span className="rounded-full px-2 py-0.5 font-medium text-white" style={{ backgroundColor: item.tag_color ?? '#6b7280' }}>
                          {item.tag_name}
                        </span>
                      ) : null}
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
