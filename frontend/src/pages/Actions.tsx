import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useToast } from '../lib/useToast'
import ToastHost from '../components/Toast'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
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
  tenant_id: number | null
  tenant_name: string | null
  title: string
  description: string | null
  due_date: string | null
  status: 'open' | 'done' | 'dismissed'
  source: 'manual' | 'ai'
  tags: ActionTag[]
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

function DismissedBadge() {
  return (
    <span className="rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700">
      Dismissed
    </span>
  )
}

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
  tags: ActionTag[]
  status: string
}

type ActionItemSuggestion = {
  id: number
  kind: 'action_item_modify' | 'action_item_delete' | 'action_item_complete'
  tenant_id: number | null
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

function joinTagNames(tags: Array<{ name: string }>) {
  return tags.map((tag) => tag.name).join(', ')
}

function TenantOrGeneralLabel({
  tenantId,
  tenantName,
  className = 'text-xs font-semibold uppercase tracking-wide text-cyan-700 hover:underline',
}: {
  tenantId: number | null
  tenantName: string | null
  className?: string
}) {
  if (tenantId == null) {
    return <span className={className}>General</span>
  }

  return (
    <Link to={`/dashboard/tenant/${tenantId}`} className={className}>
      {tenantName ?? `Tenant #${tenantId}`}
    </Link>
  )
}

export default function Actions() {
  useDocumentTitle('CRM - Actions')
  const token = useAuthStore((state) => state.token)
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined
  const { toast, showError, dismiss } = useToast()

  const [statusFilter, setStatusFilter] = useState('open')
  const [priorityFilter, setPriorityFilter] = useState<Priority | ''>('')
  const [items, setItems] = useState<ActionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [suggestions, setSuggestions] = useState<ActionItemSuggestion[]>([])
  const [loadingSuggestions, setLoadingSuggestions] = useState(true)
  const [showAddGeneralForm, setShowAddGeneralForm] = useState(false)
  const [quickAddText, setQuickAddText] = useState('')
  const [parsingQuickAdd, setParsingQuickAdd] = useState(false)
  const [allTags, setAllTags] = useState<ActionTag[]>([])
  const [newTitle, setNewTitle] = useState('')
  const [newTagIds, setNewTagIds] = useState<number[]>([])
  const [newDueDate, setNewDueDate] = useState('')
  const [newPriority, setNewPriority] = useState('')
  const [addingGeneral, setAddingGeneral] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDueDate, setEditDueDate] = useState('')
  const [editPriority, setEditPriority] = useState('')
  const [editTagIds, setEditTagIds] = useState<number[]>([])
  const [savingId, setSavingId] = useState<number | null>(null)

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

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/action-tags?active_only=true`, { headers: authHeaders })
      .then((response) => (response.ok ? response.json() : []))
      .then(setAllTags)
      .catch(() => setAllTags([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const visibleItems = priorityFilter ? items.filter((item) => item.priority === priorityFilter) : items

  const resetGeneralAddForm = () => {
    setQuickAddText('')
    setNewTitle('')
    setNewDueDate('')
    setNewTagIds([])
    setNewPriority('')
  }

  const toggleSelectedTag = (tagId: number, selectedIds: number[], setSelectedIds: (ids: number[]) => void) => {
    setSelectedIds(selectedIds.includes(tagId) ? selectedIds.filter((id) => id !== tagId) : [...selectedIds, tagId])
  }

  const handleParseGeneralQuickAdd = async () => {
    const text = quickAddText.trim()
    if (!text || parsingQuickAdd) return
    try {
      setParsingQuickAdd(true)
      const response = await fetch(`${API_BASE_URL}/api/action-items/parse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ text }),
      })
      const data = (await response.json().catch(() => null)) as { title?: string; due_date?: string | null; priority?: Priority | null; tag_ids?: number[] | null; detail?: string | null } | null
      if (!response.ok) throw new Error(data?.detail ?? 'Could not parse that into an action item')
      if (!data?.title) throw new Error('Could not parse that into an action item')
      setNewTitle(data.title)
      setNewDueDate(data.due_date ?? '')
      setNewPriority(data.priority ?? '')
      if (data.tag_ids?.length) {
        setNewTagIds((prev) => Array.from(new Set([...prev, ...data.tag_ids!])))
      }
      setQuickAddText('')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Could not parse that into an action item')
    } finally {
      setParsingQuickAdd(false)
    }
  }

  const handleAddGeneralAction = async () => {
    const title = newTitle.trim()
    if (!title || addingGeneral) return
    try {
      setAddingGeneral(true)
      const response = await fetch(`${API_BASE_URL}/api/action-items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({
          title,
          due_date: newDueDate || null,
          tag_ids: newTagIds,
          priority: newPriority || null,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) throw new Error(data?.detail ?? 'Failed to add action item')
      await load()
      resetGeneralAddForm()
      setShowAddGeneralForm(false)
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Failed to add action item')
    } finally {
      setAddingGeneral(false)
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
    if (savingId === itemId) return
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
      if (!response.ok) throw new Error()
      const updated: ActionItem = await response.json()
      setItems((current) => current.map((item) => (item.id === itemId ? updated : item)))
      cancelEdit()
    } catch {
      showError('Failed to save action item')
    } finally {
      setSavingId(null)
    }
  }

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
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Actions</h1>
            <p className="mt-1 text-sm text-gray-500">Checklist items across every tenant, added manually or suggested by AI.</p>
          </div>
          <button
            type="button"
            onClick={() => setShowAddGeneralForm((current) => !current)}
            className="rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 transition hover:border-cyan-300 hover:bg-cyan-100"
          >
            {showAddGeneralForm ? 'Close add form' : '+ Add general action'}
          </button>
        </div>

        {showAddGeneralForm ? (
          <div className="mt-3 rounded-2xl border border-cyan-200 bg-white p-4 shadow-sm">
            <div className="flex flex-col gap-3">
              <div>
                <p className="text-sm font-semibold text-gray-900">Add general action</p>
                <p className="text-xs text-gray-500">Quick parse a free-text note, then review and edit the fields before saving.</p>
              </div>
              <div className="flex flex-col gap-2 md:flex-row md:items-center">
                <input
                  type="text"
                  value={quickAddText}
                  onChange={(event) => setQuickAddText(event.target.value)}
                  placeholder="Call the plumber tomorrow"
                  className="min-w-0 flex-1 rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-300"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void handleParseGeneralQuickAdd()}
                    disabled={parsingQuickAdd || !quickAddText.trim()}
                    className="rounded-full border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {parsingQuickAdd ? 'Parsing...' : 'Parse'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      resetGeneralAddForm()
                      setShowAddGeneralForm(false)
                    }}
                    className="rounded-full border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 transition hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
              <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center">
                <input
                  type="text"
                  value={newTitle}
                  onChange={(event) => setNewTitle(event.target.value)}
                  placeholder="Action title"
                  className="min-w-0 rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-300 md:w-full"
                />
                <input
                  type="date"
                  value={newDueDate}
                  onChange={(event) => setNewDueDate(event.target.value)}
                  className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-cyan-300"
                />
                <select
                  value={newPriority}
                  onChange={(event) => setNewPriority(event.target.value)}
                  className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-cyan-300"
                >
                  <option value="">Priority</option>
                  <option value="p1">P1</option>
                  <option value="p2">P2</option>
                  <option value="p3">P3</option>
                  <option value="p4">P4</option>
                </select>
              </div>
              <TagChipSelector tags={allTags} selectedIds={newTagIds} onToggle={(tagId) => toggleSelectedTag(tagId, newTagIds, setNewTagIds)} />
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => void handleAddGeneralAction()}
                  disabled={addingGeneral || !newTitle.trim()}
                  className="rounded-full bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:bg-gray-300"
                >
                  {addingGeneral ? 'Saving...' : 'Add action'}
                </button>
              </div>
            </div>
          </div>
        ) : null}

        {!loadingSuggestions && suggestions.length > 0 ? (
          <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 p-3.5">
            <h2 className="text-sm font-semibold text-amber-900">Pending Action Changes</h2>
            <p className="mt-0.5 text-xs text-amber-700">
              The action-writer AI wants to change or remove these existing items. Nothing applies until you approve it.
            </p>
            <div className="mt-2 space-y-2">
              {suggestions.map((suggestion) => {
                const isDelete = suggestion.kind === 'action_item_delete'
                const isComplete = suggestion.kind === 'action_item_complete'
                const badgeClass = isDelete ? 'bg-rose-50 text-rose-700' : isComplete ? 'bg-emerald-50 text-emerald-700' : 'bg-cyan-50 text-cyan-700'
                const badgeLabel = isDelete ? 'Delete' : isComplete ? 'Complete' : 'Modify'

                return (
                  <div key={suggestion.id} className="rounded-xl border border-amber-200 bg-white p-2.5 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <TenantOrGeneralLabel
                            tenantId={suggestion.tenant_id}
                            tenantName={suggestion.tenant_name}
                            className="text-xs font-semibold uppercase tracking-wide text-cyan-700 hover:underline"
                          />
                          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badgeClass}`}>{badgeLabel}</span>
                        </div>

                        {isDelete ? (
                          <div className="mt-1.5">
                            <p className="text-gray-900 line-through">{suggestion.current.title}</p>
                            <p className="mt-0.5 text-xs text-rose-600">This item will be deleted.</p>
                          </div>
                        ) : isComplete ? (
                          <div className="mt-1.5">
                            <p className="text-gray-900">{suggestion.current.title}</p>
                            <p className="mt-0.5 text-xs text-emerald-600">This item will be marked done.</p>
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
                            {'tag_ids' in suggestion.proposed || 'tag_names' in suggestion.proposed ? (
                              <DiffRow label="Tags" oldValue={joinTagNames(suggestion.current.tags)} newValue={Array.isArray(suggestion.proposed.tag_names) ? (suggestion.proposed.tag_names as string[]).join(', ') : ''} />
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
                )
              })}
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
            <p className="text-sm text-gray-400">No actions yet.</p>
          ) : (
            visibleItems.map((item) => (
              <div
                key={item.id}
                className={`rounded-xl border p-3 ${item.status === 'dismissed' ? 'border-gray-200 bg-gray-50 opacity-75' : 'border-gray-200 bg-white'}`}
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
                      tags={allTags}
                      selectedIds={editTagIds}
                      onToggle={(tagId) => toggleSelectedTag(tagId, editTagIds, setEditTagIds)}
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
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <TenantOrGeneralLabel
                        tenantId={item.tenant_id}
                        tenantName={item.tenant_name}
                        className="text-xs font-semibold uppercase tracking-wide text-cyan-700 hover:underline"
                      />
                      <p className={`mt-0.5 text-sm ${item.status === 'done' ? 'text-gray-400 line-through' : 'text-gray-900'}`}>{item.title}</p>
                      {item.description ? <p className="mt-0.5 text-xs text-gray-500">{item.description}</p> : null}
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-400">
                        <span className={`rounded-full px-2 py-0.5 ${item.source === 'ai' ? 'bg-cyan-50 text-cyan-700' : 'bg-gray-100 text-gray-600'}`}>
                          {item.source === 'ai' ? 'AI' : 'Manual'}
                        </span>
                        {item.status === 'dismissed' ? <DismissedBadge /> : null}
                        {item.priority ? <span className={`rounded-full px-2 py-0.5 font-semibold ${PRIORITY_STYLE[item.priority]}`}>{PRIORITY_LABEL[item.priority]}</span> : null}
                        {item.tags.map((tag) => (
                          <span key={tag.id} className="rounded-full px-2 py-0.5 font-medium text-white" style={{ backgroundColor: tag.color }}>
                            {tag.name}
                          </span>
                        ))}
                        {item.due_date ? <span>Due {formatDisplayDateShortMonth(item.due_date)}</span> : null}
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <button type="button" onClick={() => startEdit(item)} className="rounded-full border border-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-500 hover:text-gray-700">
                        Edit
                      </button>
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
                )}
              </div>
            ))
          )}
        </div>
      </main>
      <ToastHost toast={toast} onDismiss={dismiss} />
    </>
  )
}
