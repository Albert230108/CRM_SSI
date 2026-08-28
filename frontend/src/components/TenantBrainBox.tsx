import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
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

type TenantBrainFieldValue = {
  field_definition_id: number
  key: string
  label: string
  ai_instruction: string
  value: string | null
  source: string | null
  updated_at: string | null
}

type MemoryQaMessage = { id: number; role: 'user' | 'assistant'; content: string; created_at: string }

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

  const [fields, setFields] = useState<TenantBrainFieldValue[]>([])
  const [fieldDrafts, setFieldDrafts] = useState<Record<number, string>>({})
  const [savingFieldId, setSavingFieldId] = useState<number | null>(null)
  const fieldTextareaRefs = useRef<Record<number, HTMLTextAreaElement | null>>({})


  const [qaMessages, setQaMessages] = useState<MemoryQaMessage[]>([])
  const [qaQuestion, setQaQuestion] = useState('')
  const [qaAsking, setQaAsking] = useState(false)

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

  const loadFields = async () => {
    if (!tenantId) return
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/brain-fields`, { headers: authHeaders })
      if (!response.ok) return
      const data: TenantBrainFieldValue[] = await response.json()
      setFields(data)
      setFieldDrafts(Object.fromEntries(data.map((field) => [field.field_definition_id, field.value ?? ''])))
    } catch {
      // Structured fields are a bonus panel - a failed fetch just leaves the section empty.
    }
  }

  useLayoutEffect(() => {
    for (const field of fields) {
      const textarea = fieldTextareaRefs.current[field.field_definition_id]
      if (!textarea) continue
      textarea.style.height = 'auto'
      textarea.style.height = `${textarea.scrollHeight}px`
    }
  }, [fields, fieldDrafts])

  const loadQaHistory = async () => {
    if (!tenantId) return
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/memory-qa`, { headers: authHeaders })
      if (!response.ok) return
      setQaMessages(await response.json())
    } catch {
      // Non-critical.
    }
  }

  useEffect(() => {
    setEntries([])
    setError('')
    setScanMessage('')
    setFields([])
    setFieldDrafts({})
    setQaMessages([])
    if (tenantId) {
      void loadEntries()
      void loadFields()
      void loadQaHistory()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId])

  const saveField = async (fieldDefinitionId: number) => {
    if (!tenantId) return
    try {
      setSavingFieldId(fieldDefinitionId)
      const value = fieldDrafts[fieldDefinitionId] ?? ''
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/brain-fields/${fieldDefinitionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ value: value.trim() || null }),
      })
      if (!response.ok) throw new Error('Failed to save field')
      const updated: TenantBrainFieldValue = await response.json()
      setFields((current) => current.map((field) => (field.field_definition_id === fieldDefinitionId ? updated : field)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save field')
    } finally {
      setSavingFieldId(null)
    }
  }

  const askQuestion = async () => {
    const question = qaQuestion.trim()
    if (!tenantId || !question || qaAsking) return
    try {
      setQaAsking(true)
      setQaMessages((current) => [...current, { id: -Date.now(), role: 'user', content: question, created_at: new Date().toISOString() }])
      setQaQuestion('')
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/memory-qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ question }),
      })
      if (!response.ok) throw new Error('Failed to get an answer')
      await loadQaHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get an answer')
    } finally {
      setQaAsking(false)
    }
  }

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
  const hasPriorScan = entries.some((entry) => entry.source === 'scanner')

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
          {fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
        </button>
        <button
          type="button"
          onClick={handleScan}
          disabled={!tenantId || scanning}
          className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {scanning ? (hasPriorScan ? 'Updating...' : 'Generating...') : (hasPriorScan ? 'Update' : 'Generate')}
        </button>
      </div>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullscreen, isActive, scanning, tenantId, entries.length])

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

      <div className="min-h-0 flex-1 space-y-3 overflow-auto">
        {tenantId && fields.length > 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white p-2">
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">Structured Fields</p>
            <div className="space-y-1.5">
              {fields.map((field) => (
                <div key={field.field_definition_id} className="flex items-center gap-1.5">
                  <span className="w-28 shrink-0 truncate text-xs font-medium text-gray-600" title={field.ai_instruction}>
                    {field.label}
                  </span>
                  <textarea
                    ref={(element) => {
                      fieldTextareaRefs.current[field.field_definition_id] = element
                    }}
                    value={fieldDrafts[field.field_definition_id] ?? ''}
                    onChange={(event) =>
                      setFieldDrafts((current) => ({ ...current, [field.field_definition_id]: event.target.value }))
                    }
                    onBlur={() => {
                      if ((fieldDrafts[field.field_definition_id] ?? '') !== (field.value ?? '')) void saveField(field.field_definition_id)
                    }}
                    placeholder="Not set"
                    rows={2}
                    className="min-h-[2.25rem] min-w-0 flex-1 resize-none overflow-hidden rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 outline-none focus:border-cyan-300"
                  />
                  {savingFieldId === field.field_definition_id ? <span className="shrink-0 text-[10px] text-gray-400">Saving...</span> : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}


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

      {tenantId ? (
        <div className="shrink-0 space-y-1.5 border-t border-gray-100 pt-1.5">
          {qaMessages.length > 0 ? (
            <div className="max-h-32 space-y-1.5 overflow-auto rounded-lg border border-gray-100 bg-gray-50/60 p-1.5">
              {qaMessages.map((message) => (
                <p key={message.id} className={`text-xs ${message.role === 'user' ? 'font-medium text-gray-800' : 'text-gray-600'}`}>
                  <span className="font-semibold">{message.role === 'user' ? 'You: ' : 'AI: '}</span>
                  {message.content}
                </p>
              ))}
            </div>
          ) : null}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={qaQuestion}
              onChange={(event) => setQaQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void askQuestion()
              }}
              disabled={qaAsking}
              placeholder="Ask a question about this tenant..."
              className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none transition focus:border-cyan-300 disabled:cursor-not-allowed disabled:bg-gray-50"
            />
            <button
              type="button"
              onClick={askQuestion}
              disabled={!qaQuestion.trim() || qaAsking}
              className="shrink-0 rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-medium text-cyan-700 transition hover:border-cyan-300 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {qaAsking ? 'Asking...' : 'Ask'}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
