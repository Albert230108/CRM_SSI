import { useEffect, useState, type ReactNode } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatDisplayDateShortMonth } from '../lib/date'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type Priority = 'p1' | 'p2' | 'p3' | 'p4'

type ActionTag = {
  id: number
  name: string
  color: string
}

type ActionItem = {
  id: number
  title: string
  description: string | null
  due_date: string | null
  status: 'open' | 'done' | 'dismissed'
  source: 'manual' | 'ai'
  tags: ActionTag[]
  priority: Priority | null
  recurrence_interval_days: number | null
  recurrence_anchor: 'due_date' | 'completed_at' | null
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

const PRIORITY_STYLE: Record<Priority, string> = {
  p1: 'bg-rose-50 text-rose-700',
  p2: 'bg-orange-50 text-orange-700',
  p3: 'bg-amber-50 text-amber-700',
  p4: 'bg-blue-50 text-blue-700',
}

const PRIORITY_LABEL: Record<Priority, string> = { p1: 'P1', p2: 'P2', p3: 'P3', p4: 'P4' }

const DismissedBadge = () => (
  <span className="rounded-full border border-gray-200 bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-500">
    Dismissed
  </span>
)

function TagChipSelector({
  tags,
  selectedIds,
  onToggle,
  disabled = false,
}: {
  tags: ActionTag[]
  selectedIds: number[]
  onToggle: (tagId: number) => void
  disabled?: boolean
}) {
  if (tags.length === 0) {
    return <span className="text-xs text-gray-400">No tags configured.</span>
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((tag) => {
        const selected = selectedIds.includes(tag.id)
        return (
          <button
            key={tag.id}
            type="button"
            onClick={() => onToggle(tag.id)}
            disabled={disabled}
            aria-pressed={selected}
            className={`rounded-full border px-2.5 py-1 text-xs font-medium transition ${
              selected ? 'border-transparent text-white shadow-sm' : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
            } disabled:cursor-not-allowed disabled:opacity-50`}
            style={selected ? { backgroundColor: tag.color } : undefined}
          >
            {tag.name}
          </button>
        )
      })}
    </div>
  )
}

export default function TenantActionsBox({ tenantId, isActive = true, onActionsChange }: Props) {
  const token = useAuthStore((state) => state.token)
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined

  const [items, setItems] = useState<ActionItem[]>([])
  const [tags, setTags] = useState<ActionTag[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [quickText, setQuickText] = useState('')
  const [parsing, setParsing] = useState(false)

  const [newTitle, setNewTitle] = useState('')
  const [newDueDate, setNewDueDate] = useState('')
  const [newTagIds, setNewTagIds] = useState<number[]>([])
  const [newPriority, setNewPriority] = useState('')
  const [repeatEnabled, setRepeatEnabled] = useState(false)
  const [repeatDays, setRepeatDays] = useState('7')
  const [adding, setAdding] = useState(false)

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDueDate, setEditDueDate] = useState('')
  const [editPriority, setEditPriority] = useState('')
  const [editTagIds, setEditTagIds] = useState<number[]>([])
  const [savingId, setSavingId] = useState<number | null>(null)

  const [fullscreen, setFullscreen] = useState(false)
  const [showAddModal, setShowAddModal] = useState(false)

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
    fetch(`${API_BASE_URL}/api/action-tags?active_only=true`, { headers: authHeaders })
      .then((response) => (response.ok ? response.json() : []))
      .then(setTags)
      .catch(() => setTags([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setItems([])
    setError('')
    if (tenantId) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId])

  useEffect(() => {
    if (!fullscreen || showAddModal) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreen, showAddModal])

  useEffect(() => {
    if (!showAddModal) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShowAddModal(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [showAddModal])

  useEffect(() => {
    if (!isActive || !onActionsChange) return
    onActionsChange(
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => setFullscreen((current) => !current)}
          aria-label={fullscreen ? 'Exit fullscreen' : 'Open tenant actions fullscreen'}
          title={fullscreen ? 'Exit fullscreen (Esc)' : 'Open tenant actions fullscreen'}
          className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 transition hover:border-gray-300 hover:bg-gray-50"
        >
          {fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
        </button>
        <button
          type="button"
          onClick={() => setShowAddModal(true)}
          disabled={!tenantId}
          aria-label="Add new task"
          title="Add new task"
          className="rounded border border-gray-200 bg-white px-1.5 py-0.5 text-xs font-semibold text-gray-600 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          +
        </button>
      </div>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullscreen, isActive, onActionsChange, tenantId])

  const resetAddForm = () => {
    setNewTitle('')
    setNewDueDate('')
    setNewTagIds([])
    setNewPriority('')
    setRepeatEnabled(false)
    setRepeatDays('7')
  }

  const toggleSelectedTag = (tagId: number, selectedIds: number[], setSelectedIds: (ids: number[]) => void) => {
    setSelectedIds(selectedIds.includes(tagId) ? selectedIds.filter((id) => id !== tagId) : [...selectedIds, tagId])
  }

  const handleAdd = async () => {
    const title = newTitle.trim()
    if (!tenantId || !title || adding) return
    try {
      setAdding(true)
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/action-items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({
          title,
          due_date: newDueDate || null,
          tag_ids: newTagIds,
          priority: newPriority || null,
          recurrence_interval_days: repeatEnabled && repeatDays ? Number(repeatDays) : null,
          recurrence_anchor: 'due_date',
        }),
      })
      if (!response.ok) throw new Error('Failed to add action item')
      const item: ActionItem = await response.json()
      setItems((current) => [item, ...current])
      resetAddForm()
      setShowAddModal(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add action item')
    } finally {
      setAdding(false)
    }
  }

  const handleQuickAdd = async () => {
    const text = quickText.trim()
    if (!tenantId || !text || parsing) return
    try {
      setParsing(true)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/action-items/parse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ text }),
      })
      if (!response.ok) throw new Error('Could not parse that into a task')
      const parsed: { title: string; due_date: string | null; priority: Priority | null; tag_ids?: number[] | null } = await response.json()
      setNewTitle(parsed.title)
      setNewDueDate(parsed.due_date ?? '')
      setNewPriority(parsed.priority ?? '')
      if (parsed.tag_ids?.length) {
        setNewTagIds((prev) => Array.from(new Set([...prev, ...parsed.tag_ids!])))
      }
      setQuickText('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not parse that into a task')
    } finally {
      setParsing(false)
    }
  }

  const startEdit = (item: ActionItem) => {
    setEditingId(item.id)
    setEditTitle(item.title)
    setEditDueDate(item.due_date ?? '')
    setEditPriority(item.priority ?? '')
    setEditTagIds(item.tags.map((tag) => tag.id))
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditTitle('')
    setEditDueDate('')
    setEditPriority('')
    setEditTagIds([])
  }

  const saveEdit = async (itemId: number) => {
    if (!tenantId || savingId === itemId) return
    try {
      setSavingId(itemId)
      const response = await fetch(`${API_BASE_URL}/api/action-items/${itemId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({
          title: editTitle.trim(),
          due_date: editDueDate || null,
          priority: editPriority || null,
          tag_ids: editTagIds,
        }),
      })
      if (!response.ok) throw new Error('Failed to save action item')
      const updated: ActionItem = await response.json()
      setItems((current) => current.map((item) => (item.id === itemId ? updated : item)))
      cancelEdit()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save action item')
    } finally {
      setSavingId(null)
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

  const subtitleMessage = !tenantId ? 'No tenant selected' : loading ? 'Loading...' : ''
  const containerClassName = fullscreen
    ? 'fixed inset-0 z-50 flex h-screen w-screen min-w-0 flex-col gap-1.5 bg-white p-4'
    : 'flex h-full w-full min-w-0 flex-col gap-1.5'

  return (
    <div className={containerClassName}>
      {fullscreen ? (
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => setFullscreen(false)}
            className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 transition hover:border-gray-300 hover:bg-gray-50"
          >
            Exit fullscreen
          </button>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            disabled={!tenantId}
            aria-label="Add new task"
            title="Add new task"
            className="rounded border border-gray-200 bg-white px-1.5 py-0.5 text-xs font-semibold text-gray-600 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            +
          </button>
        </div>
      ) : null}
      {subtitleMessage ? <p className="text-sm text-gray-500">{subtitleMessage}</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      {showAddModal ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setShowAddModal(false)
          }}
        >
          <div className="w-full max-w-2xl rounded-2xl border border-gray-200 bg-white p-4 shadow-xl">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-gray-900">Add new task</p>
                <p className="text-xs text-gray-500">Quick parse or fill in the task manually.</p>
              </div>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="rounded-full border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-500 transition hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>

            <div className="space-y-3">
              <div className="flex shrink-0 items-center gap-2">
                <input
                  type="text"
                  value={quickText}
                  onChange={(event) => setQuickText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void handleQuickAdd()
                  }}
                  disabled={!tenantId || parsing}
                  placeholder={tenantId ? 'Quick add: "Call guest tomorrow 5pm"...' : ''}
                  className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none transition focus:border-cyan-300 disabled:cursor-not-allowed disabled:bg-gray-50"
                />
                <button
                  type="button"
                  onClick={handleQuickAdd}
                  disabled={!tenantId || !quickText.trim() || parsing}
                  className="shrink-0 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600 transition hover:border-gray-300 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {parsing ? 'Parsing...' : 'Parse'}
                </button>
              </div>

              <div className="flex shrink-0 flex-wrap items-center gap-2">
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
                <select
                  value={newPriority}
                  onChange={(event) => setNewPriority(event.target.value)}
                  disabled={!tenantId}
                  className="shrink-0 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 outline-none focus:border-cyan-300 disabled:cursor-not-allowed disabled:bg-gray-50"
                >
                  <option value="">Priority</option>
                  <option value="p1">P1</option>
                  <option value="p2">P2</option>
                  <option value="p3">P3</option>
                  <option value="p4">P4</option>
                </select>
                <button
                  type="button"
                  onClick={() => setNewTagIds([])}
                  disabled={!tenantId || newTagIds.length === 0}
                  className="shrink-0 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-500 transition hover:border-gray-300 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Clear tags
                </button>
                <button
                  type="button"
                  onClick={handleAdd}
                  disabled={!tenantId || !newTitle.trim() || adding}
                  className="shrink-0 rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-medium text-cyan-700 transition hover:border-cyan-300 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Add
                </button>
              </div>

              <TagChipSelector tags={tags} selectedIds={newTagIds} onToggle={(tagId) => toggleSelectedTag(tagId, newTagIds, setNewTagIds)} disabled={!tenantId} />

              <label className="flex shrink-0 items-center gap-1.5 text-xs text-gray-500">
                <input type="checkbox" checked={repeatEnabled} onChange={(event) => setRepeatEnabled(event.target.checked)} disabled={!tenantId} />
                Repeat every
                <input
                  type="number"
                  min={1}
                  value={repeatDays}
                  onChange={(event) => setRepeatDays(event.target.value)}
                  disabled={!tenantId || !repeatEnabled}
                  className="w-14 rounded border border-gray-200 bg-white px-1.5 py-0.5 text-xs text-gray-700 outline-none disabled:bg-gray-50"
                />
                days
              </label>
            </div>
          </div>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 space-y-2 overflow-auto">
        {!tenantId ? null : !loading && items.length === 0 ? (
          <p className="text-sm text-gray-400">Nothing to do yet.</p>
        ) : (
          items.map((item) => (
            <div
              key={item.id}
              className={`rounded-xl border p-2 text-sm ${
                item.status === 'dismissed' ? 'border-gray-200 bg-gray-50 opacity-75' : 'border-gray-200 bg-white'
              }`}
            >
              {editingId === item.id ? (
                <div className="space-y-2">
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(event) => setEditTitle(event.target.value)}
                    className="w-full rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-cyan-300"
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="date"
                      value={editDueDate}
                      onChange={(event) => setEditDueDate(event.target.value)}
                      className="shrink-0 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 outline-none focus:border-cyan-300"
                    />
                    <select
                      value={editPriority}
                      onChange={(event) => setEditPriority(event.target.value)}
                      className="shrink-0 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 outline-none focus:border-cyan-300"
                    >
                      <option value="">Priority</option>
                      <option value="p1">P1</option>
                      <option value="p2">P2</option>
                      <option value="p3">P3</option>
                      <option value="p4">P4</option>
                    </select>
                  </div>
                  <TagChipSelector
                    tags={tags}
                    selectedIds={editTagIds}
                    onToggle={(tagId) => toggleSelectedTag(tagId, editTagIds, setEditTagIds)}
                    disabled={!tenantId}
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void saveEdit(item.id)}
                      disabled={savingId === item.id || !editTitle.trim()}
                      className="rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-medium text-cyan-700 transition hover:border-cyan-300 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {savingId === item.id ? 'Saving...' : 'Save'}
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="rounded-full border border-gray-200 px-3 py-1 text-xs font-medium text-gray-500 transition hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <p className={`whitespace-pre-wrap ${item.status === 'done' ? 'text-gray-400 line-through' : 'text-gray-900'}`}>{item.title}</p>
                  {item.description ? <p className="mt-0.5 text-xs text-gray-500">{item.description}</p> : null}
                  <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${SOURCE_STYLE[item.source]}`}>{item.source === 'ai' ? 'AI' : 'Manual'}</span>
                      {item.status === 'dismissed' ? <DismissedBadge /> : null}
                      {item.priority ? <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${PRIORITY_STYLE[item.priority]}`}>{PRIORITY_LABEL[item.priority]}</span> : null}
                      {item.tags.map((tag) => (
                        <span key={tag.id} className="rounded-full px-2 py-0.5 text-xs font-medium text-white" style={{ backgroundColor: tag.color }}>
                          {tag.name}
                        </span>
                      ))}
                      {item.recurrence_interval_days ? <span className="text-xs text-gray-400">↻ every {item.recurrence_interval_days}d</span> : null}
                      {item.due_date ? <span className="text-xs text-gray-400">Due {formatDisplayDateShortMonth(item.due_date)}</span> : null}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <button type="button" onClick={() => startEdit(item)} className="text-xs font-medium text-gray-500 hover:text-gray-700">
                        Edit
                      </button>
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
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
