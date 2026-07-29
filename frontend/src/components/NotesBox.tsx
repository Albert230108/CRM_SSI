import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type TenantNotes = {
  id: number
  notes: string | null
}

type NotesBoxProps = {
  tenantId?: number
  onReady?: (tenantId: number) => void
}

export default function NotesBox({ tenantId, onReady }: NotesBoxProps) {
  const token = useAuthStore((state) => state.token)
  const [savedNotes, setSavedNotes] = useState('')
  const [draftNotes, setDraftNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [syncWarning, setSyncWarning] = useState('')
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    if (!tenantId) {
      setSavedNotes('')
      setDraftNotes('')
      setError('')
      setSyncWarning('')
      setLoading(false)
      return
    }

    const controller = new AbortController()
    const activeTenantId = tenantId
    const loadTenant = async () => {
      try {
        setLoading(true)
        setError('')
        setSyncWarning('')
        const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('Failed to load tenant notes')
        const data: TenantNotes = await response.json()
        setSavedNotes(data.notes ?? '')
        setDraftNotes(data.notes ?? '')
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load tenant notes')
      } finally {
        setLoading(false)
        onReady?.(activeTenantId)
      }
    }

    loadTenant()
    return () => controller.abort()
  }, [tenantId, token])

  const isDirty = draftNotes !== savedNotes

  const handleSave = async () => {
    if (!tenantId || saving) return
    try {
      setSaving(true)
      setError('')
      setSyncWarning('')
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/notes`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ notes: draftNotes }),
      })
      if (!response.ok) throw new Error('Failed to save notes')
      const data: { notes: string | null; beds24_synced: boolean; beds24_error?: string } = await response.json()
      setSavedNotes(data.notes ?? '')
      setDraftNotes(data.notes ?? '')
      if (!data.beds24_synced) {
        setSyncWarning(`Saved locally - Beds24 sync failed${data.beds24_error ? `: ${data.beds24_error}` : ''}`)
      } else {
        setSavedFlash(true)
        window.setTimeout(() => setSavedFlash(false), 2000)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save notes')
    } finally {
      setSaving(false)
    }
  }

  const subtitleMessage = !tenantId ? 'No tenant selected' : loading ? 'Loading...' : ''

  return (
    <div className="flex h-full w-full min-w-0 flex-col gap-1.5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Notes</h2>
          {subtitleMessage ? <p className="mt-1 text-sm text-gray-500">{subtitleMessage}</p> : null}
        </div>
        <button
          type="button"
          onClick={handleSave}
          disabled={!tenantId || !isDirty || saving}
          className="shrink-0 rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-medium text-cyan-700 transition hover:border-cyan-300 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? 'Saving...' : savedFlash ? 'Saved!' : 'Save'}
        </button>
      </div>

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {syncWarning ? <p className="text-sm text-amber-500">{syncWarning}</p> : null}

      <textarea
        value={draftNotes}
        onChange={(event) => setDraftNotes(event.target.value)}
        disabled={!tenantId}
        placeholder={tenantId ? 'Add notes for this tenant...' : ''}
        className="min-h-0 flex-1 w-full resize-none rounded-xl border border-gray-200 bg-white p-2 text-sm text-gray-900 outline-none transition focus:border-cyan-300 disabled:cursor-not-allowed disabled:bg-gray-50"
      />
    </div>
  )
}
