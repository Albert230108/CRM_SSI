import { useEffect, useState, type ReactNode } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type ActionItem = {
  id: number
  title: string
  description: string | null
  due_date: string | null
  status: 'open' | 'done' | 'dismissed'
  source: 'manual' | 'ai'
}

type Props = {
  tenantId?: number
  isActive?: boolean
  onActionsChange?: (actions: ReactNode) => void
}

const SOURCE_STYLE: Record<ActionItem['source'], string> = {
  manual: 'bg-gray-100 text-gray-600',
  ai: 'bg-cyan-50 text-cyan-700',
}

export default function TenantActionsBox({ tenantId, isActive = true, onActionsChange }: Props) {
  const token = useAuthStore((state) => state.token)
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined

  const [items, setItems] = useState<ActionItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newDueDate, setNewDueDate] = useState('')
  const [adding, setAdding] = useState(false)

  const load = async () => {
    if (!tenantId) return
    try {
      setLoading(true)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/action-items`, { headers: authHeaders })
      if (!response.ok) throw new Error('Failed to load action items')
      setItems(await response.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load action items')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setItems([])
    setError('')
    if (tenantId) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId])

  const handleAdd = async () => {
    const title = newTitle.trim()
    if (!tenantId || !title || adding) return
    try {
      setAdding(true)
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/action-items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ title, due_date: newDueDate || null }),
      })
      if (!response.ok) throw new Error('Failed to add action item')
      const item: ActionItem = await response.json()
      setItems((current) => [item, ...current])
      setNewTitle('')
      setNewDueDate('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add action item')
    } finally {
      setAdding(false)
    }
  }

  const transition = async (id: number, action: 'complete' | 'dismiss' | 'reopen') => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/action-items/${id}/${action}`, { method: 'POST', headers: authHeaders })
      if (!response.ok) throw new Error('Failed to update action item')
      const updated: ActionItem = await response.json()
      setItems((current) => current.map((item) => (item.id === id ? updated : item)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update action item')
    }
  }

  useEffect(() => {
    if (!isActive || !onActionsChange) return
    onActionsChange(null)
  }, [isActive, onActionsChange])

  const subtitleMessage = !tenantId ? 'No tenant selected' : loading ? 'Loading...' : ''

  return (
    <div className="flex h-full w-full min-w-0 flex-col gap-1.5">
      {subtitleMessage ? <p className="text-sm text-gray-500">{subtitleMessage}</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <div className="flex shrink-0 items-center gap-2">
        <input
          type="text"
          value={newTitle}
          onChange={(event) => setNewTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void handleAdd()
          }}
          disabled={!tenantId}
          placeholder={tenantId ? 'Add an action item...' : ''}
          className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none transition focus:border-cyan-300 disabled:cursor-not-allowed disabled:bg-gray-50"
        />
        <input
          type="date"
          value={newDueDate}
          onChange={(event) => setNewDueDate(event.target.value)}
          disabled={!tenantId}
          className="shrink-0 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 outline-none focus:border-cyan-300 disabled:cursor-not-allowed disabled:bg-gray-50"
        />
        <button
          type="button"
          onClick={handleAdd}
          disabled={!tenantId || !newTitle.trim() || adding}
          className="shrink-0 rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-medium text-cyan-700 transition hover:border-cyan-300 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Add
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-auto">
        {!tenantId ? null : !loading && items.length === 0 ? (
          <p className="text-sm text-gray-400">Nothing to do yet.</p>
        ) : (
          items.map((item) => (
            <div key={item.id} className="rounded-xl border border-gray-200 bg-white p-2 text-sm">
              <p className={`whitespace-pre-wrap ${item.status === 'done' ? 'text-gray-400 line-through' : 'text-gray-900'}`}>{item.title}</p>
              {item.description ? <p className="mt-0.5 text-xs text-gray-500">{item.description}</p> : null}
              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-1.5">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${SOURCE_STYLE[item.source]}`}>{item.source === 'ai' ? 'AI' : 'Manual'}</span>
                  {item.due_date ? <span className="text-xs text-gray-400">Due {item.due_date}</span> : null}
                </div>
                <div className="flex shrink-0 gap-2">
                  {item.status === 'open' ? (
                    <>
                      <button type="button" onClick={() => transition(item.id, 'complete')} className="text-xs font-medium text-emerald-600 hover:text-emerald-700">
                        Done
                      </button>
                      <button type="button" onClick={() => transition(item.id, 'dismiss')} className="text-xs font-medium text-rose-500 hover:text-rose-600">
                        Dismiss
                      </button>
                    </>
                  ) : (
                    <button type="button" onClick={() => transition(item.id, 'reopen')} className="text-xs font-medium text-gray-500 hover:text-gray-700">
                      Reopen
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
