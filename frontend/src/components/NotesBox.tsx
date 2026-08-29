import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useAuthStore } from '../store/authStore'
import { useNotesDraftStore } from '../store/notesDraftStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const DRAFT_AUTOSAVE_DELAY_MS = 3000

type TenantNotes = {
  id: number
  notes: string | null
  draft_notes: string | null
}

type NotesBoxProps = {
  tenantId?: number
  onReady?: (tenantId: number) => void
  isActive?: boolean
  onActionsChange?: (actions: ReactNode) => void
}

export default function NotesBox({ tenantId, onReady, isActive = true, onActionsChange }: NotesBoxProps) {
  const token = useAuthStore((state) => state.token)
  const [savedNotes, setSavedNotes] = useState('')
  const [draftNotes, setDraftNotes] = useState('')
  const [hasRemoteDraft, setHasRemoteDraft] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [syncWarning, setSyncWarning] = useState('')
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    if (!tenantId) {
      setSavedNotes('')
      setDraftNotes('')
      setHasRemoteDraft(false)
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
        const committedNotes = data.notes ?? ''
        setSavedNotes(committedNotes)
        // A pending draft (left by anyone, in any session) takes priority so editing
        // continues from where it was left off, rather than silently discarding it.
        setDraftNotes(data.draft_notes ?? committedNotes)
        setHasRemoteDraft(Boolean(data.draft_notes) && data.draft_notes !== committedNotes)
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

  const persistDraft = (keepalive: boolean) => {
    if (!tenantId || draftNotes === savedNotes) return
    fetch(`${API_BASE_URL}/api/tenants/${tenantId}/notes/draft`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ draft_notes: draftNotes }),
      keepalive,
    })
      .then(() => setHasRemoteDraft(true))
      .catch(() => {
        // Best-effort: the next debounce tick or navigation-time flush will retry.
      })
  }

  const handleDiscardDraft = () => {
    setDraftNotes(savedNotes)
    setHasRemoteDraft(false)
    if (!tenantId) return
    fetch(`${API_BASE_URL}/api/tenants/${tenantId}/notes/draft`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    }).catch(() => {})
  }

  // Debounced auto-save of the in-progress edit as a draft, so it survives navigation,
  // reload, or a crash even if the user never clicks Save. Also clears a stale remote
  // draft once the text is edited back to match the last saved value.
  useEffect(() => {
    if (!tenantId) return
    const timeoutId = window.setTimeout(() => {
      if (draftNotes !== savedNotes) {
        persistDraft(false)
      } else if (hasRemoteDraft) {
        handleDiscardDraft()
      }
    }, DRAFT_AUTOSAVE_DELAY_MS)
    return () => window.clearTimeout(timeoutId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftNotes, savedNotes, tenantId])

  const commitSave = async () => {
    if (!tenantId) return
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
      setHasRemoteDraft(false)
      if (!data.beds24_synced) {
        setSyncWarning(`Saved locally - Beds24 sync failed${data.beds24_error ? `: ${data.beds24_error}` : ''}`)
      } else {
        setSavedFlash(true)
        window.setTimeout(() => setSavedFlash(false), 2000)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save notes')
      throw err
    } finally {
      setSaving(false)
    }
  }

  const handleSave = () => {
    if (!tenantId || saving) return
    commitSave().catch(() => {
      // Surfaced via the `error` state above; nothing further to do here.
    })
  }

  // Latest closures for the store to call from outside React (tenant-switch clicks,
  // Navbar navigation, beforeunload) without re-registering on every keystroke.
  const commitSaveRef = useRef(commitSave)
  const discardDraftRef = useRef(handleDiscardDraft)
  const flushDraftRef = useRef(() => persistDraft(true))
  useEffect(() => {
    commitSaveRef.current = commitSave
    discardDraftRef.current = handleDiscardDraft
    flushDraftRef.current = () => persistDraft(true)
  })

  useEffect(() => {
    if (!tenantId) return
    useNotesDraftStore.getState().registerHandlers({
      tenantId,
      save: () => commitSaveRef.current(),
      discard: () => discardDraftRef.current(),
      flushDraft: () => flushDraftRef.current(),
    })
    return () => useNotesDraftStore.getState().clearHandlers(tenantId)
  }, [tenantId])

  useEffect(() => {
    if (!tenantId) return
    useNotesDraftStore.getState().setDirty(tenantId, isDirty)
  }, [tenantId, isDirty])

  const subtitleMessage = !tenantId ? 'No tenant selected' : loading ? 'Loading...' : ''

  useEffect(() => {
    if (!isActive || !onActionsChange) return
    onActionsChange(
      <div className="flex shrink-0 items-center gap-2">
        {isDirty ? (
          <button
            type="button"
            onClick={handleDiscardDraft}
            disabled={saving}
            className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-500 transition hover:border-gray-300 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Discard draft
          </button>
        ) : null}
        <button
          type="button"
          onClick={handleSave}
          disabled={!tenantId || !isDirty || saving}
          className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 transition hover:border-brand-300 hover:bg-brand-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? 'Saving...' : savedFlash ? 'Saved!' : 'Save'}
        </button>
      </div>,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isActive, isDirty, saving, savedFlash, tenantId])

  return (
    <div className="flex h-full w-full min-w-0 flex-col gap-1.5">
      {subtitleMessage ? <p className="text-sm text-gray-500">{subtitleMessage}</p> : null}

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {syncWarning ? <p className="text-sm text-amber-500">{syncWarning}</p> : null}
      <textarea
        value={draftNotes}
        onChange={(event) => setDraftNotes(event.target.value)}
        disabled={!tenantId}
        placeholder={tenantId ? 'Add notes for this tenant...' : ''}
        className="min-h-0 flex-1 w-full resize-none rounded-xl border border-gray-200 bg-white p-2 text-sm text-gray-900 outline-none transition focus:border-brand-300 disabled:cursor-not-allowed disabled:bg-gray-50"
      />
    </div>
  )
}
