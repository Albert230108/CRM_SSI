import { useEffect, useState, type ReactNode } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type BrainEntry = {
  id: number
  content: string
  source: 'manual' | 'planner' | 'scanner'
  created_by_user_id: number | null
  created_by_email: string | null
  created_at: string
  updated_at: string
}

type TenantBrainBoxProps = {
  tenantId?: number
  isActive?: boolean
  onActionsChange?: (actions: ReactNode) => void
}

const SOURCE_LABEL: Record<BrainEntry['source'], string> = {
  manual: 'Manual',
  planner: 'AI',
  scanner: 'AI scan',
}

const SOURCE_STYLE: Record<BrainEntry['source'], string> = {
  manual: 'bg-gray-100 text-gray-600',
  planner: 'bg-cyan-50 text-cyan-700',
  scanner: 'bg-indigo-50 text-indigo-700',
}

export default function TenantBrainBox({ tenantId, isActive = true, onActionsChange }: TenantBrainBoxProps) {
  const token = useAuthStore((state) => state.token)
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined

  const [entries, setEntries] = useState<BrainEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [newContent, setNewContent] = useState('')
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingContent, setEditingContent] = useState('')
  const [scanning, setScanning] = useState(false)
  const [scanMessage, setScanMessage] = useState('')
  const [fullscreen, setFullscreen] = useState(false)

  const loadEntries = async () => {
    if (!tenantId) return
    try {
      setLoading(true)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/brain`, { headers: authHeaders })
      if (!response.ok) throw new Error('Failed to load tenant brain')
      setEntries(await response.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tenant brain')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setEntries([])
    setError('')
    setScanMessage('')
    if (tenantId) void loadEntries()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId])

  useEffect(() => {
    if (!fullscreen) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreen])

  const handleAdd = async () => {
    const content = newContent.trim()
    if (!tenantId || !content || adding) return
    try {
      setAdding(true)
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/brain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ content }),
      })
      if (!response.ok) throw new Error('Failed to add entry')
      const entry: BrainEntry = await response.json()
      setEntries((current) => [entry, ...current])
      setNewContent('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add entry')
    } finally {
      setAdding(false)
    }
  }

  const startEdit = (entry: BrainEntry) => {
    setEditingId(entry.id)
    setEditingContent(entry.content)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditingContent('')
  }

  const saveEdit = async (entryId: number) => {
    if (!tenantId) return
    const content = editingContent.trim()
    if (!content) return
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/brain/${entryId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ content }),
      })
      if (!response.ok) throw new Error('Failed to save entry')
      const updated: BrainEntry = await response.json()
      setEntries((current) => current.map((entry) => (entry.id === entryId ? updated : entry)))
      cancelEdit()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save entry')
    }
  }

  const handleDelete = async (entryId: number) => {
    if (!tenantId) return
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/brain/${entryId}`, {
        method: 'DELETE',
        headers: authHeaders,
      })
      if (!response.ok) throw new Error('Failed to delete entry')
      setEntries((current) => current.filter((entry) => entry.id !== entryId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete entry')
    }
  }

  const handleScan = async () => {
    if (!tenantId || scanning) return
    try {
      setScanning(true)
      setScanMessage('')
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/brain/scan`, {
        method: 'POST',
        headers: authHeaders,
      })
      if (!response.ok) throw new Error('Failed to scan tenant history')
      const added: BrainEntry[] = await response.json()
      setEntries((current) => [...added, ...current])
      setScanMessage(added.length ? `Added ${added.length} entr${added.length === 1 ? 'y' : 'ies'}.` : 'Nothing new found.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to scan tenant history')
    } finally {
      setScanning(false)
    }
  }

  const subtitleMessage = !tenantId ? 'No tenant selected' : loading ? 'Loading...' : ''

  useEffect(() => {
    if (!isActive || !onActionsChange) return
    onActionsChange(
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => setFullscreen((current) => !current)}
          aria-label={fullscreen ? 'Exit fullscreen' : 'Open tenant brain fullscreen'}
          title={fullscreen ? 'Exit fullscreen (Esc)' : 'Open tenant brain fullscreen'}
          className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 transition hover:border-gray-300 hover:bg-gray-50"
        >
          {fullscreen ? 'Exit' : 'Fullscreen'}
        </button>
        <button
          type="button"
          onClick={handleScan}
          disabled={!tenantId || scanning}
          className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {scanning ? 'Scanning...' : 'Generate initial brain'}
        </button>
      </div>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullscreen, isActive, scanning, tenantId])

  return (
    <div
      className={
        fullscreen
          ? 'fixed inset-0 z-50 flex h-screen w-screen min-w-0 flex-col gap-1.5 bg-white p-4'
          : 'flex h-full w-full min-w-0 flex-col gap-1.5'
      }
    >
      {fullscreen ? (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => setFullscreen(false)}
            className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 transition hover:border-gray-300 hover:bg-gray-50"
          >
            Exit fullscreen
          </button>
        </div>
      ) : null}
      {subtitleMessage ? <p className="text-sm text-gray-500">{subtitleMessage}</p> : null}

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {scanMessage ? <p className="text-xs text-indigo-600">{scanMessage}</p> : null}

      <div className="flex shrink-0 items-center gap-2">
        <input
          type="text"
          value={newContent}
          onChange={(event) => setNewContent(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void handleAdd()
          }}
          disabled={!tenantId}
          placeholder={tenantId ? 'Add something worth remembering...' : ''}
          className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none transition focus:border-cyan-300 disabled:cursor-not-allowed disabled:bg-gray-50"
        />
        <button
          type="button"
          onClick={handleAdd}
          disabled={!tenantId || !newContent.trim() || adding}
          className="shrink-0 rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-medium text-cyan-700 transition hover:border-cyan-300 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Add
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-auto">
        {!tenantId ? null : !loading && entries.length === 0 ? (
          <p className="text-sm text-gray-400">Nothing remembered yet.</p>
        ) : (
          entries.map((entry) => (
            <div key={entry.id} className="rounded-xl border border-gray-200 bg-white p-2 text-sm">
              {editingId === entry.id ? (
                <div className="space-y-1.5">
                  <textarea
                    value={editingContent}
                    onChange={(event) => setEditingContent(event.target.value)}
                    className="w-full resize-none rounded-lg border border-gray-200 p-1.5 text-sm text-gray-900 outline-none focus:border-cyan-300"
                    rows={2}
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => saveEdit(entry.id)}
                      className="rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-0.5 text-xs font-medium text-cyan-700"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="rounded-full border border-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-500"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <p className="whitespace-pre-wrap text-gray-900">{entry.content}</p>
                  <div className="mt-1.5 flex items-center justify-between gap-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${SOURCE_STYLE[entry.source]}`}>
                      {SOURCE_LABEL[entry.source]}
                    </span>
                    <div className="flex shrink-0 gap-2">
                      <button type="button" onClick={() => startEdit(entry)} className="text-xs font-medium text-gray-500 hover:text-gray-700">
                        Edit
                      </button>
                      <button type="button" onClick={() => handleDelete(entry.id)} className="text-xs font-medium text-rose-500 hover:text-rose-600">
                        Delete
                      </button>
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
