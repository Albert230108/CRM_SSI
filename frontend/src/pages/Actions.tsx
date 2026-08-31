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
  triggers_planner?: boolean
}

type ActionItem = {
  id: number
  tenant_id: number | null
  tenant_name: string | null
  title: string
  description: string | null
  ai_instruction: string | null
  due_date: string | null
  due_time: string | null
  status: 'open' | 'done' | 'dismissed'
  source: 'manual' | 'ai'
  tags: ActionTag[]
  priority: Priority | null
  created_at: string
}

type SortField = 'due_date' | 'priority' | 'created_at'
type SortDir = 'asc' | 'desc'
type DueBucket = 'overdue' | 'today' | 'tomorrow' | 'upcoming' | 'none'
type ViewScope = 'all' | 'tenant' | 'general'
type TagMatch = 'any' | 'all'
type GroupBy = 'none' | 'date' | 'priority' | 'status' | 'tenant'
type Layout = 'list' | 'board'

type SavedView = {
  id: number
  name: string
  position: number
  status: string | null
  priority: Priority | null
  tag_ids: number[]
  tag_match: TagMatch
  due_buckets: DueBucket[]
  scope: ViewScope
  group_by: GroupBy
  layout: Layout
  sort_field: SortField
  sort_dir: SortDir
}

const GROUP_BY_OPTIONS: Array<{ id: GroupBy; label: string }> = [
  { id: 'none', label: 'None' },
  { id: 'date', label: 'Date' },
  { id: 'priority', label: 'Priority' },
  { id: 'status', label: 'Status' },
  { id: 'tenant', label: 'Tenant' },
]

const DUE_BUCKET_ORDER: DueBucket[] = ['overdue', 'today', 'tomorrow', 'upcoming', 'none']
const DUE_BUCKET_LABEL: Record<DueBucket, string> = {
  overdue: 'Overdue',
  today: 'Today',
  tomorrow: 'Tomorrow',
  upcoming: 'Upcoming',
  none: 'No date',
}

const SORT_FIELDS: Array<{ id: SortField; label: string }> = [
  { id: 'due_date', label: 'Due date' },
  { id: 'priority', label: 'Priority' },
  { id: 'created_at', label: 'Created' },
]

const SCOPES: Array<{ id: ViewScope; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'tenant', label: 'Tenant' },
  { id: 'general', label: 'General' },
]

function priorityRank(priority: Priority | null): number {
  return priority ? Number(priority.slice(1)) : 99
}

function dueBucketOf(dueDate: string | null): DueBucket {
  if (!dueDate) return 'none'
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const tomorrow = new Date(today)
  tomorrow.setDate(tomorrow.getDate() + 1)
  const due = new Date(`${dueDate}T00:00:00`)
  if (due < today) return 'overdue'
  if (due.getTime() === today.getTime()) return 'today'
  if (due.getTime() === tomorrow.getTime()) return 'tomorrow'
  return 'upcoming'
}

type ActionGroup = { key: string; label: string; items: ActionItem[] }

// Splits the already-filtered-and-sorted items into ordered sections/columns. Item order within
// each group is preserved from the incoming sort. Empty groups are dropped by the caller.
function groupItems(items: ActionItem[], groupBy: GroupBy): ActionGroup[] {
  if (groupBy === 'none') {
    return [{ key: 'all', label: 'All actions', items }]
  }
  const buckets = new Map<string, ActionItem[]>()
  const push = (key: string, item: ActionItem) => {
    const existing = buckets.get(key)
    if (existing) existing.push(item)
    else buckets.set(key, [item])
  }

  if (groupBy === 'date') {
    for (const item of items) push(dueBucketOf(item.due_date), item)
    return DUE_BUCKET_ORDER.filter((key) => buckets.has(key)).map((key) => ({ key, label: DUE_BUCKET_LABEL[key], items: buckets.get(key)! }))
  }
  if (groupBy === 'priority') {
    for (const item of items) push(item.priority ?? 'none', item)
    const order = ['p1', 'p2', 'p3', 'p4', 'none']
    const label = (key: string) => (key === 'none' ? 'No priority' : PRIORITY_LABEL[key as Priority])
    return order.filter((key) => buckets.has(key)).map((key) => ({ key, label: label(key), items: buckets.get(key)! }))
  }
  if (groupBy === 'status') {
    for (const item of items) push(item.status, item)
    const order = ['open', 'done', 'dismissed']
    const label: Record<string, string> = { open: 'Open', done: 'Done', dismissed: 'Dismissed' }
    return order.filter((key) => buckets.has(key)).map((key) => ({ key, label: label[key] ?? key, items: buckets.get(key)! }))
  }
  // tenant: group by tenant, ordered by name A→Z with General (tenant-less) last.
  for (const item of items) push(item.tenant_id == null ? 'general' : `t:${item.tenant_id}`, item)
  const entries = Array.from(buckets.entries())
  const named = entries.filter(([key]) => key !== 'general').sort((a, b) => (a[1][0].tenant_name ?? '').localeCompare(b[1][0].tenant_name ?? ''))
  const general = entries.filter(([key]) => key === 'general')
  return [...named, ...general].map(([key, groupItemsList]) => ({
    key,
    label: key === 'general' ? 'General' : groupItemsList[0].tenant_name ?? `Tenant #${groupItemsList[0].tenant_id}`,
    items: groupItemsList,
  }))
}

function formatDueTime(dueTime: string | null): string {
  // API returns HH:MM:SS; show HH:MM.
  return dueTime ? dueTime.slice(0, 5) : ''
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
  ai_instruction: string | null
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
  className = 'text-xs font-semibold uppercase tracking-wide text-brand-700 hover:underline',
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
  const [tagFilterIds, setTagFilterIds] = useState<number[]>([])
  const [tagMatch, setTagMatch] = useState<TagMatch>('any')
  const [dueBuckets, setDueBuckets] = useState<DueBucket[]>([])
  const [scopeFilter, setScopeFilter] = useState<ViewScope>('all')
  const [groupBy, setGroupBy] = useState<GroupBy>('none')
  const [layout, setLayout] = useState<Layout>('list')
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  const [sortField, setSortField] = useState<SortField>('due_date')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
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
  const [newDueTime, setNewDueTime] = useState('')
  const [newPriority, setNewPriority] = useState('')
  const [newAiInstruction, setNewAiInstruction] = useState('')
  const [addingGeneral, setAddingGeneral] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDueDate, setEditDueDate] = useState('')
  const [editDueTime, setEditDueTime] = useState('')
  const [editPriority, setEditPriority] = useState('')
  const [editAiInstruction, setEditAiInstruction] = useState('')
  const [editTagIds, setEditTagIds] = useState<number[]>([])
  const [savingId, setSavingId] = useState<number | null>(null)

  const [savedViews, setSavedViews] = useState<SavedView[]>([])
  const [activeViewId, setActiveViewId] = useState<number | null>(null)
  const [showSaveView, setShowSaveView] = useState(false)
  const [newViewName, setNewViewName] = useState('')
  const [savingView, setSavingView] = useState(false)

  const load = async (signal?: AbortSignal) => {
    setLoading(true)
    try {
      const params = statusFilter ? `?status=${statusFilter}` : ''
      const response = await fetch(`${API_BASE_URL}/api/action-items${params}`, { headers: authHeaders, signal })
      if (!response.ok) throw new Error()
      setItems(await response.json())
    } catch (error) {
      // A superseded status switch aborts the in-flight request; ignore it so an older response
      // can't land last (stale-response race) and don't surface a spurious error toast.
      if ((error as { name?: string })?.name !== 'AbortError') showError('Failed to load action items')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
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

  const loadSavedViews = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/action-saved-views`, { headers: authHeaders })
      setSavedViews(response.ok ? await response.json() : [])
    } catch {
      setSavedViews([])
    }
  }

  useEffect(() => {
    loadSavedViews()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const applyView = (view: SavedView) => {
    setActiveViewId(view.id)
    setStatusFilter(view.status ?? '')
    setPriorityFilter(view.priority ?? '')
    setTagFilterIds(view.tag_ids)
    setTagMatch(view.tag_match)
    setDueBuckets(view.due_buckets ?? [])
    setScopeFilter(view.scope)
    setGroupBy(view.group_by)
    setLayout(view.layout)
    setSortField(view.sort_field)
    setSortDir(view.sort_dir)
  }

  const currentFilterPayload = () => ({
    status: statusFilter || null,
    priority: priorityFilter || null,
    tag_ids: tagFilterIds,
    tag_match: tagMatch,
    due_buckets: dueBuckets,
    scope: scopeFilter,
    group_by: groupBy,
    layout,
    sort_field: sortField,
    sort_dir: sortDir,
  })

  const handleSaveView = async () => {
    const name = newViewName.trim()
    if (!name || savingView) return
    try {
      setSavingView(true)
      const response = await fetch(`${API_BASE_URL}/api/action-saved-views`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ name, ...currentFilterPayload() }),
      })
      if (!response.ok) throw new Error()
      const created: SavedView = await response.json()
      setSavedViews((current) => [...current, created])
      setActiveViewId(created.id)
      setShowSaveView(false)
      setNewViewName('')
    } catch {
      showError('Failed to save view')
    } finally {
      setSavingView(false)
    }
  }

  const handleUpdateActiveView = async () => {
    if (activeViewId == null) return
    try {
      const response = await fetch(`${API_BASE_URL}/api/action-saved-views/${activeViewId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ ...currentFilterPayload(), clear_status: !statusFilter, clear_priority: !priorityFilter }),
      })
      if (!response.ok) throw new Error()
      const updated: SavedView = await response.json()
      setSavedViews((current) => current.map((view) => (view.id === updated.id ? updated : view)))
    } catch {
      showError('Failed to update view')
    }
  }

  const handleDeleteView = async (viewId: number) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/action-saved-views/${viewId}`, { method: 'DELETE', headers: authHeaders })
      if (!response.ok && response.status !== 204) throw new Error()
      setSavedViews((current) => current.filter((view) => view.id !== viewId))
      if (activeViewId === viewId) setActiveViewId(null)
    } catch {
      showError('Failed to delete view')
    }
  }

  const clearActiveView = () => {
    setActiveViewId(null)
    setPriorityFilter('')
    setTagFilterIds([])
    setTagMatch('any')
    setDueBuckets([])
    setScopeFilter('all')
    setGroupBy('none')
    setLayout('list')
    setSortField('due_date')
    setSortDir('asc')
  }

  const toggleDueBucket = (bucket: DueBucket) => {
    setDueBuckets((current) => (current.includes(bucket) ? current.filter((value) => value !== bucket) : [...current, bucket]))
  }

  const selectLayout = (next: Layout) => {
    setLayout(next)
    // A board needs a grouping to form columns; default to date when none is set.
    if (next === 'board' && groupBy === 'none') setGroupBy('date')
  }

  const toggleGroupCollapsed = (key: string) => {
    setCollapsedGroups((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // The action-items API returns tags without the triggers_planner flag, so resolve it from the
  // full tag palette (allTags) to decide whether to show the "Planner" badge.
  const plannerTagIds = new Set(allTags.filter((tag) => tag.triggers_planner).map((tag) => tag.id))

  const visibleItems = items
    .filter((item) => (priorityFilter ? item.priority === priorityFilter : true))
    .filter((item) => (scopeFilter === 'tenant' ? item.tenant_id != null : scopeFilter === 'general' ? item.tenant_id == null : true))
    .filter((item) => (dueBuckets.length === 0 ? true : dueBuckets.includes(dueBucketOf(item.due_date))))
    .filter((item) => {
      if (tagFilterIds.length === 0) return true
      const itemTagIds = new Set(item.tags.map((tag) => tag.id))
      return tagMatch === 'all' ? tagFilterIds.every((id) => itemTagIds.has(id)) : tagFilterIds.some((id) => itemTagIds.has(id))
    })
    .slice()
    .sort((a, b) => {
      let cmp = 0
      if (sortField === 'due_date') {
        // Nulls always last, regardless of direction.
        if (!a.due_date && !b.due_date) cmp = 0
        else if (!a.due_date) return 1
        else if (!b.due_date) return -1
        else cmp = a.due_date.localeCompare(b.due_date) || formatDueTime(a.due_time).localeCompare(formatDueTime(b.due_time))
      } else if (sortField === 'priority') {
        cmp = priorityRank(a.priority) - priorityRank(b.priority)
      } else {
        cmp = a.created_at.localeCompare(b.created_at)
      }
      return sortDir === 'desc' ? -cmp : cmp
    })

  const groups = groupItems(visibleItems, groupBy)

  const renderActionCard = (item: ActionItem) => (
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
            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-brand-300"
          />
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              value={editDueDate}
              onChange={(event) => setEditDueDate(event.target.value)}
              className="shrink-0 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 outline-none focus:border-brand-300"
            />
            <input
              type="time"
              value={editDueTime}
              onChange={(event) => setEditDueTime(event.target.value)}
              aria-label="Due time"
              title="Due time (used to trigger the planner)"
              className="shrink-0 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 outline-none focus:border-brand-300"
            />
            <select
              value={editPriority}
              onChange={(event) => setEditPriority(event.target.value)}
              className="shrink-0 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-700 outline-none focus:border-brand-300"
            >
              <option value="">Priority</option>
              <option value="p1">P1</option>
              <option value="p2">P2</option>
              <option value="p3">P3</option>
              <option value="p4">P4</option>
            </select>
          </div>
          <textarea
            value={editAiInstruction}
            onChange={(event) => setEditAiInstruction(event.target.value)}
            placeholder="AI instruction (optional) — what the planner should do when this action comes due"
            rows={2}
            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-900 outline-none focus:border-brand-300"
          />
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
              className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 transition hover:border-brand-300 hover:bg-brand-100 disabled:cursor-not-allowed disabled:opacity-50"
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
              className="text-xs font-semibold uppercase tracking-wide text-brand-700 hover:underline"
            />
            <p className={`mt-0.5 text-sm ${item.status === 'done' ? 'text-gray-400 line-through' : 'text-gray-900'}`}>{item.title}</p>
            {item.description ? <p className="mt-0.5 text-xs text-gray-500">{item.description}</p> : null}
            {item.ai_instruction ? (
              <p className="mt-0.5 text-xs text-brand-700">
                <span className="font-semibold">AI:</span> {item.ai_instruction}
              </p>
            ) : null}
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-400">
              <span className={`rounded-full px-2 py-0.5 ${item.source === 'ai' ? 'bg-brand-50 text-brand-700' : 'bg-gray-100 text-gray-600'}`}>
                {item.source === 'ai' ? 'AI' : 'Manual'}
              </span>
              {item.status === 'dismissed' ? <DismissedBadge /> : null}
              {item.priority ? <span className={`rounded-full px-2 py-0.5 font-semibold ${PRIORITY_STYLE[item.priority]}`}>{PRIORITY_LABEL[item.priority]}</span> : null}
              {item.tags.map((tag) => (
                <span key={tag.id} className="rounded-full px-2 py-0.5 font-medium text-white" style={{ backgroundColor: tag.color }}>
                  {tag.name}
                </span>
              ))}
              {item.tenant_id != null && item.tags.some((tag) => plannerTagIds.has(tag.id)) ? (
                <span className="rounded-full border border-brand-200 bg-brand-50 px-2 py-0.5 font-semibold text-brand-700" title="This action triggers the planner at its due date/time">
                  Planner
                </span>
              ) : null}
              {item.due_date ? (
                <span>
                  Due {formatDisplayDateShortMonth(item.due_date)}
                  {item.due_time ? ` at ${formatDueTime(item.due_time)}` : ''}
                </span>
              ) : null}
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
  )

  const renderGroupHeader = (group: ActionGroup) => (
    <button
      type="button"
      onClick={() => toggleGroupCollapsed(group.key)}
      className="flex w-full items-center gap-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700"
    >
      <span>{collapsedGroups.has(group.key) ? '▸' : '▾'}</span>
      <span>{group.label}</span>
      <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold text-gray-500">{group.items.length}</span>
    </button>
  )

  const resetGeneralAddForm = () => {
    setQuickAddText('')
    setNewTitle('')
    setNewDueDate('')
    setNewDueTime('')
    setNewTagIds([])
    setNewPriority('')
    setNewAiInstruction('')
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
          ai_instruction: newAiInstruction.trim() || null,
          due_date: newDueDate || null,
          due_time: newDueTime || null,
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
    setEditDueTime(formatDueTime(item.due_time))
    setEditPriority(item.priority ?? '')
    setEditAiInstruction(item.ai_instruction ?? '')
    setEditTagIds(item.tags.map((tag) => tag.id))
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditTitle('')
    setEditDueDate('')
    setEditDueTime('')
    setEditPriority('')
    setEditAiInstruction('')
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
          due_time: editDueTime || null,
          clear_due_time: !editDueTime,
          priority: editPriority || null,
          ai_instruction: editAiInstruction.trim() || null,
          clear_ai_instruction: !editAiInstruction.trim(),
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
      <main className="mx-auto animate-slide-up max-w-5xl px-6 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Actions</h1>
            <p className="mt-1 text-sm text-gray-500">Checklist items across every tenant, added manually or suggested by AI.</p>
          </div>
          <button
            type="button"
            onClick={() => setShowAddGeneralForm((current) => !current)}
            className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 transition hover:border-brand-300 hover:bg-brand-100"
          >
            {showAddGeneralForm ? 'Close add form' : '+ Add general action'}
          </button>
        </div>

        {showAddGeneralForm ? (
          <div className="mt-3 rounded-2xl border border-brand-200 bg-white p-4 shadow-sm">
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
                  className="min-w-0 flex-1 rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-300"
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
              <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto_auto] md:items-center">
                <input
                  type="text"
                  value={newTitle}
                  onChange={(event) => setNewTitle(event.target.value)}
                  placeholder="Action title"
                  className="min-w-0 rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-300 md:w-full"
                />
                <input
                  type="date"
                  value={newDueDate}
                  onChange={(event) => setNewDueDate(event.target.value)}
                  className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-brand-300"
                />
                <input
                  type="time"
                  value={newDueTime}
                  onChange={(event) => setNewDueTime(event.target.value)}
                  aria-label="Due time"
                  title="Due time (used to trigger the planner)"
                  className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-brand-300"
                />
                <select
                  value={newPriority}
                  onChange={(event) => setNewPriority(event.target.value)}
                  className="rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-brand-300"
                >
                  <option value="">Priority</option>
                  <option value="p1">P1</option>
                  <option value="p2">P2</option>
                  <option value="p3">P3</option>
                  <option value="p4">P4</option>
                </select>
              </div>
              <textarea
                value={newAiInstruction}
                onChange={(event) => setNewAiInstruction(event.target.value)}
                placeholder="AI instruction (optional) — what the planner should do when this action comes due"
                rows={2}
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-300"
              />
              <TagChipSelector tags={allTags} selectedIds={newTagIds} onToggle={(tagId) => toggleSelectedTag(tagId, newTagIds, setNewTagIds)} />
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => void handleAddGeneralAction()}
                  disabled={addingGeneral || !newTitle.trim()}
                  className="rounded-full bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-gray-300"
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
                const badgeClass = isDelete ? 'bg-rose-50 text-rose-700' : isComplete ? 'bg-emerald-50 text-emerald-700' : 'bg-brand-50 text-brand-700'
                const badgeLabel = isDelete ? 'Delete' : isComplete ? 'Complete' : 'Modify'

                return (
                  <div key={suggestion.id} className="rounded-xl border border-amber-200 bg-white p-2.5 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <TenantOrGeneralLabel
                            tenantId={suggestion.tenant_id}
                            tenantName={suggestion.tenant_name}
                            className="text-xs font-semibold uppercase tracking-wide text-brand-700 hover:underline"
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
                            {'ai_instruction' in suggestion.proposed ? (
                              <DiffRow label="AI" oldValue={suggestion.current.ai_instruction ?? ''} newValue={String(suggestion.proposed.ai_instruction ?? '')} />
                            ) : null}
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

        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-b border-gray-200 pb-2">
          <button
            type="button"
            onClick={clearActiveView}
            className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
              activeViewId === null ? 'bg-brand-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-100'
            }`}
          >
            All actions
          </button>
          {savedViews.map((view) => (
            <span
              key={view.id}
              className={`inline-flex items-center gap-1 rounded-full text-xs font-semibold transition ${
                activeViewId === view.id ? 'bg-brand-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-100'
              }`}
            >
              <button type="button" onClick={() => applyView(view)} className="py-1.5 pl-3 pr-1">
                {view.name}
              </button>
              <button
                type="button"
                onClick={() => void handleDeleteView(view.id)}
                aria-label={`Delete ${view.name} tab`}
                className={`pr-2.5 ${activeViewId === view.id ? 'text-white/80 hover:text-white' : 'text-gray-400 hover:text-gray-600'}`}
              >
                ×
              </button>
            </span>
          ))}
          {activeViewId !== null ? (
            <button
              type="button"
              onClick={() => void handleUpdateActiveView()}
              className="rounded-full border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-600 transition hover:bg-gray-100"
            >
              Update tab
            </button>
          ) : showSaveView ? (
            <span className="inline-flex items-center gap-1.5">
              <input
                type="text"
                value={newViewName}
                onChange={(event) => setNewViewName(event.target.value)}
                placeholder="Tab name"
                className="w-32 rounded-full border border-gray-200 px-3 py-1.5 text-xs text-gray-900 outline-none focus:border-brand-300"
              />
              <button
                type="button"
                onClick={() => void handleSaveView()}
                disabled={savingView || !newViewName.trim()}
                className="rounded-full bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                {savingView ? 'Saving...' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowSaveView(false)
                  setNewViewName('')
                }}
                className="rounded-full border border-gray-200 px-3 py-1.5 text-xs font-semibold text-gray-500 transition hover:bg-gray-50"
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setShowSaveView(true)}
              className="rounded-full border border-dashed border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-500 transition hover:bg-gray-100"
            >
              + Save current as tab
            </button>
          )}
        </div>

        <div className="mt-3 flex gap-1.5">
          {STATUS_FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              onClick={() => setStatusFilter(filter.id)}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                statusFilter === filter.id ? 'bg-brand-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-100'
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
                priorityFilter === filter.id ? 'bg-brand-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-100'
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <div className="flex gap-1.5">
            {SCOPES.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setScopeFilter(option.id)}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                  scopeFilter === option.id ? 'bg-brand-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-100'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {DUE_BUCKET_ORDER.map((bucket) => (
              <button
                key={bucket}
                type="button"
                onClick={() => toggleDueBucket(bucket)}
                aria-pressed={dueBuckets.includes(bucket)}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                  dueBuckets.includes(bucket) ? 'bg-brand-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-100'
                }`}
              >
                {DUE_BUCKET_LABEL[bucket]}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <label className="text-xs font-semibold text-gray-500">Sort</label>
            <select
              value={sortField}
              onChange={(event) => setSortField(event.target.value as SortField)}
              className="rounded-full border border-gray-300 px-2.5 py-1 text-xs text-gray-700 outline-none focus:border-brand-300"
            >
              {SORT_FIELDS.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setSortDir((current) => (current === 'asc' ? 'desc' : 'asc'))}
              aria-label="Toggle sort direction"
              className="rounded-full border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 transition hover:bg-gray-100"
            >
              {sortDir === 'asc' ? '↑ Asc' : '↓ Desc'}
            </button>
          </div>
        </div>

        {allTags.length > 0 ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-gray-500">Tags</span>
            <TagChipSelector tags={allTags} selectedIds={tagFilterIds} onToggle={(tagId) => toggleSelectedTag(tagId, tagFilterIds, setTagFilterIds)} />
            {tagFilterIds.length > 1 ? (
              <button
                type="button"
                onClick={() => setTagMatch((current) => (current === 'any' ? 'all' : 'any'))}
                className="rounded-full border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-600 transition hover:bg-gray-100"
              >
                Match: {tagMatch === 'any' ? 'Any' : 'All'}
              </button>
            ) : null}
          </div>
        ) : null}

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-gray-500">Group by</span>
          <div className="flex gap-1.5">
            {GROUP_BY_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setGroupBy(option.id)}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                  groupBy === option.id ? 'bg-brand-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-100'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="ml-auto inline-flex overflow-hidden rounded-full border border-gray-300">
            <button
              type="button"
              onClick={() => selectLayout('list')}
              className={`px-3 py-1 text-xs font-semibold transition ${layout === 'list' ? 'bg-brand-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
            >
              List
            </button>
            <button
              type="button"
              onClick={() => selectLayout('board')}
              className={`px-3 py-1 text-xs font-semibold transition ${layout === 'board' ? 'bg-brand-600 text-white' : 'text-gray-700 hover:bg-gray-100'}`}
            >
              Board
            </button>
          </div>
        </div>

        {loading ? (
          <p className="mt-3 text-sm text-gray-500">Loading...</p>
        ) : visibleItems.length === 0 ? (
          <p className="mt-3 text-sm text-gray-400">No actions yet.</p>
        ) : layout === 'board' ? (
          <div className="mt-3 flex gap-3 overflow-x-auto pb-2">
            {groups.map((group) => (
              <div key={group.key} className="flex w-72 shrink-0 flex-col rounded-2xl border border-gray-200 bg-gray-50 p-2">
                <div className="sticky top-0 mb-2 px-1">{renderGroupHeader(group)}</div>
                <div className="space-y-2">{group.items.map((item) => renderActionCard(item))}</div>
              </div>
            ))}
          </div>
        ) : groupBy === 'none' ? (
          <div className="mt-3 space-y-2 stagger-list">{visibleItems.map((item) => renderActionCard(item))}</div>
        ) : (
          <div className="mt-3 space-y-4">
            {groups.map((group) => (
              <div key={group.key}>
                <div className="mb-1.5">{renderGroupHeader(group)}</div>
                {collapsedGroups.has(group.key) ? null : <div className="space-y-2 stagger-list">{group.items.map((item) => renderActionCard(item))}</div>}
              </div>
            ))}
          </div>
        )}
      </main>
      <ToastHost toast={toast} onDismiss={dismiss} />
    </>
  )
}
