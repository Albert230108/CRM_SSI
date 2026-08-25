import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { getAiSettingsReturnHref } from '../lib/aiSettingsNavigation'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export type BrainNode = {
  id: number
  parent_id: number | null
  path: string
  slug: string
  title: string
  content: string | null
  color: string | null
  position: number
  is_active: boolean
  children: BrainNode[]
}

type EditorState = {
  title: string
  slug: string
  content: string
  color: string
  is_active: boolean
}

const emptyEditor: EditorState = { title: '', slug: '', content: '', color: '', is_active: true }

const COLOR_PRESETS = [
  '#ef4444',
  '#f97316',
  '#f59e0b',
  '#84cc16',
  '#22c55e',
  '#14b8a6',
  '#06b6d4',
  '#3b82f6',
  '#8b5cf6',
  '#ec4899',
]

/** Depth-first walk so the tree can be searched and flattened without re-fetching. */
function flatten(nodes: BrainNode[], depth = 0): { node: BrainNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...flatten(node.children, depth + 1)])
}

function findNode(nodes: BrainNode[], id: number): BrainNode | null {
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findNode(node.children, id)
    if (found) return found
  }
  return null
}

export default function BrainSections() {
  useDocumentTitle('CRM - Brain')
  const token = useAuthStore((state) => state.token)
  const location = useLocation()
  const [tree, setTree] = useState<BrainNode[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [editor, setEditor] = useState<EditorState>(emptyEditor)
  const [creatingUnder, setCreatingUnder] = useState<number | null | 'none'>('none')
  const [filter, setFilter] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [copiedPath, setCopiedPath] = useState('')

  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : undefined),
    [token],
  )

  const loadTree = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/api/brain-sections`, { headers: authHeaders })
    if (!response.ok) {
      setMessage('Failed to load the brain')
      setLoading(false)
      return
    }
    setTree(await response.json())
    setLoading(false)
  }, [authHeaders])

  useEffect(() => {
    void loadTree()
  }, [loadTree])

  const selected = selectedId === null ? null : findNode(tree, selectedId)
  const rows = flatten(tree)
  const visibleRows = filter.trim()
    ? rows.filter(({ node }) =>
        `${node.path} ${node.title}`.toLowerCase().includes(filter.trim().toLowerCase()),
      )
    : rows

  const selectNode = (node: BrainNode) => {
    setCreatingUnder('none')
    setSelectedId(node.id)
    setMessage('')
    setEditor({
      title: node.title,
      slug: node.slug,
      content: node.content ?? '',
      color: node.color ?? '',
      is_active: node.is_active,
    })
  }

  const startCreate = (parentId: number | null) => {
    setSelectedId(null)
    setCreatingUnder(parentId)
    setMessage('')
    // New subsections default to their parent's color; top-level sections start with none.
    const parent = parentId === null ? null : findNode(tree, parentId)
    setEditor({ ...emptyEditor, color: parent?.color ?? '' })
  }

  const save = async () => {
    if (!editor.title.trim()) {
      setMessage('A title is required')
      return
    }
    setSaving(true)
    setMessage('')
    try {
      const isCreate = creatingUnder !== 'none'
      const url = isCreate
        ? `${API_BASE_URL}/api/brain-sections`
        : `${API_BASE_URL}/api/brain-sections/${selectedId}`
      const response = await fetch(url, {
        method: isCreate ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          title: editor.title,
          // An empty slug lets the backend derive one from the title on create, and keeps the
          // existing slug (and therefore every {{brain:...}} reference) untouched on update.
          slug: editor.slug.trim() || null,
          content: editor.content,
          color: editor.color || null,
          is_active: editor.is_active,
          ...(isCreate ? { parent_id: creatingUnder } : {}),
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setMessage(data?.detail ?? 'Failed to save the section')
        return
      }
      await loadTree()
      setCreatingUnder('none')
      setSelectedId(data.id)
      setEditor({
        title: data.title,
        slug: data.slug,
        content: data.content ?? '',
        color: data.color ?? '',
        is_active: data.is_active,
      })
      setMessage('Saved')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (node: BrainNode) => {
    const hasChildren = node.children.length > 0
    const confirmed = window.confirm(
      hasChildren
        ? `Delete "${node.title}" and all ${flatten(node.children).length} section(s) underneath it?`
        : `Delete "${node.title}"?`,
    )
    if (!confirmed) return
    const response = await fetch(
      `${API_BASE_URL}/api/brain-sections/${node.id}${hasChildren ? '?cascade=true' : ''}`,
      { method: 'DELETE', headers: authHeaders },
    )
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setMessage(data?.detail ?? 'Failed to delete the section')
      return
    }
    setSelectedId(null)
    setCreatingUnder('none')
    setMessage('Deleted')
    await loadTree()
  }

  const move = async (node: BrainNode, direction: -1 | 1) => {
    const response = await fetch(`${API_BASE_URL}/api/brain-sections/${node.id}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ parent_id: node.parent_id, position: Math.max(0, node.position + direction) }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setMessage(data?.detail ?? 'Failed to reorder')
      return
    }
    await loadTree()
  }

  const copyToken = async (path: string) => {
    const token_ = `{{brain:${path}}}`
    try {
      await navigator.clipboard.writeText(token_)
      setCopiedPath(path)
      window.setTimeout(() => setCopiedPath(''), 1500)
    } catch {
      setMessage(`Copy failed. The token is ${token_}`)
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-4">
      <Link to={getAiSettingsReturnHref(location.search, '/settings')} className="text-sm text-cyan-700 hover:underline">&larr; Back to Settings</Link>
      <h1 className="mt-1.5 text-2xl font-semibold text-gray-900">AI Brain</h1>
      <p className="mt-1.5 text-sm text-gray-500">
        One shared knowledge tree. Reference a section from any AI reply template with its{' '}
        <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">{'{{brain:path}}'}</code> token, or attach it to a
        template directly. Referencing a section also pulls in everything nested underneath it.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Sections</h2>
            <button
              type="button"
              onClick={() => startCreate(null)}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
            >
              + Top level
            </button>
          </div>

          <input
            type="text"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter by path or title..."
            className="mt-2.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
          />

          {loading ? (
            <p className="mt-3 text-sm text-gray-500">Loading...</p>
          ) : visibleRows.length === 0 ? (
            <p className="mt-3 text-sm text-gray-500">
              {rows.length === 0 ? 'No sections yet. Create a top-level section to start.' : 'Nothing matches.'}
            </p>
          ) : (
            <ul className="mt-2.5 space-y-0.5">
              {visibleRows.map(({ node, depth }) => (
                <li key={node.id}>
                  <div
                    className={`group flex items-center gap-1.5 rounded-lg px-2 py-1.5 ${
                      selectedId === node.id ? 'bg-indigo-50' : 'hover:bg-gray-50'
                    }`}
                    style={{
                      paddingLeft: `${8 + depth * 16}px`,
                      borderLeft: `3px solid ${node.color || 'transparent'}`,
                    }}
                  >
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full border border-gray-300"
                      style={{ backgroundColor: node.color || 'transparent' }}
                      title={node.color ?? 'No color'}
                    />
                    <button
                      type="button"
                      onClick={() => selectNode(node)}
                      className="flex-1 truncate text-left text-sm text-gray-900"
                      title={node.path}
                    >
                      {node.title}
                      {!node.is_active ? <span className="ml-2 text-xs text-amber-600">inactive</span> : null}
                      <span className="ml-2 text-xs text-gray-400">{node.path}</span>
                    </button>
                    <div className="flex shrink-0 items-center gap-1 opacity-0 transition group-hover:opacity-100">
                      <button
                        type="button"
                        onClick={() => copyToken(node.path)}
                        className="rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-200"
                        title="Copy the {{brain:...}} token"
                      >
                        {copiedPath === node.path ? 'copied' : 'token'}
                      </button>
                      <button
                        type="button"
                        onClick={() => move(node, -1)}
                        className="rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-200"
                        title="Move up"
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        onClick={() => move(node, 1)}
                        className="rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-200"
                        title="Move down"
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        onClick={() => startCreate(node.id)}
                        className="rounded px-1.5 py-0.5 text-xs text-indigo-600 hover:bg-indigo-100"
                        title="Add a subsection"
                      >
                        +
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(node)}
                        className="rounded px-1.5 py-0.5 text-xs text-red-600 hover:bg-red-50"
                        title="Delete"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
          {creatingUnder === 'none' && !selected ? (
            <p className="text-sm text-gray-500">Select a section to edit it, or create a new one.</p>
          ) : (
            <div className="space-y-3">
              <h2 className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">
                {creatingUnder !== 'none'
                  ? creatingUnder === null
                    ? 'New top-level section'
                    : `New subsection of ${findNode(tree, creatingUnder)?.path ?? ''}`
                  : `Editing ${selected?.path ?? ''}`}
              </h2>

              <div>
                <label className="block text-sm font-medium text-gray-700" htmlFor="brain-title">Title</label>
                <input
                  id="brain-title"
                  type="text"
                  value={editor.title}
                  onChange={(event) => setEditor({ ...editor, title: event.target.value })}
                  placeholder="Cancellation policy"
                  className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700" htmlFor="brain-slug">
                  Slug <span className="font-normal text-gray-500">— part of the token path; leave blank to derive it from the title</span>
                </label>
                <input
                  id="brain-slug"
                  type="text"
                  value={editor.slug}
                  onChange={(event) => setEditor({ ...editor, slug: event.target.value })}
                  placeholder="cancellation-policy"
                  className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 font-mono text-sm text-gray-900 outline-none focus:border-cyan-500"
                />
                {creatingUnder === 'none' && selected ? (
                  <p className="mt-1 text-xs text-amber-600">
                    Changing the slug rewrites this section's path and every path underneath it. Templates using the
                    old <code>{'{{brain:...}}'}</code> token will stop resolving.
                  </p>
                ) : null}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700" htmlFor="brain-content">
                  Content <span className="font-normal text-gray-500">— leave blank for a pure container</span>
                </label>
                <textarea
                  id="brain-content"
                  rows={14}
                  value={editor.content}
                  onChange={(event) => setEditor({ ...editor, content: event.target.value })}
                  className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Tenant placeholders such as <code>{'{{first_name}}'}</code> work here, and so do nested{' '}
                  <code>{'{{brain:other.path}}'}</code> references.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700">Color</label>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  {COLOR_PRESETS.map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => setEditor({ ...editor, color: preset })}
                      className={`h-6 w-6 rounded-full border-2 ${
                        editor.color.toLowerCase() === preset ? 'border-gray-900' : 'border-transparent'
                      }`}
                      style={{ backgroundColor: preset }}
                      title={preset}
                      aria-label={`Set color ${preset}`}
                    />
                  ))}
                  <input
                    type="color"
                    value={editor.color || '#ffffff'}
                    onChange={(event) => setEditor({ ...editor, color: event.target.value })}
                    className="h-6 w-8 cursor-pointer rounded border border-gray-300 bg-white p-0"
                    title="Custom color"
                    aria-label="Custom color"
                  />
                  {editor.color ? (
                    <button
                      type="button"
                      onClick={() => setEditor({ ...editor, color: '' })}
                      className="rounded-lg border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50"
                    >
                      Clear
                    </button>
                  ) : null}
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={editor.is_active}
                  onChange={(event) => setEditor({ ...editor, is_active: event.target.checked })}
                />
                Active — inactive sections resolve to nothing and are hidden from the planner
              </label>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={save}
                  disabled={saving}
                  className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
                {creatingUnder !== 'none' ? (
                  <button
                    type="button"
                    onClick={() => setCreatingUnder('none')}
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                ) : null}
                {message ? <p className="text-sm text-gray-600">{message}</p> : null}
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  )
}
