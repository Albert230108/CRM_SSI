import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type AiAutoDraftItem = {
  id: number
  tenant_id: number
  tenant_name: string | null
  channel: string
  generated_text: string
  quoted_context: string | null
  status: string
  scheduled_send_at: string | null
  created_at: string
}

export default function AiPendingDrafts() {
  useDocumentTitle('CRM - AI Drafts')
  const token = useAuthStore((state) => state.token)
  const navigate = useNavigate()
  const [drafts, setDrafts] = useState<AiAutoDraftItem[]>([])
  const [loading, setLoading] = useState(false)
  const [sendErrors, setSendErrors] = useState<Record<number, string>>({})
  const [redoOpenDraftId, setRedoOpenDraftId] = useState<number | null>(null)
  const [redoWhat, setRedoWhat] = useState('')
  const [redoWhy, setRedoWhy] = useState('')
  const [redoSubmitting, setRedoSubmitting] = useState(false)
  const [reasons, setReasons] = useState<Record<number, string>>({})

  const loadDrafts = useCallback(async () => {
    if (!token) return
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts`, { headers: { Authorization: `Bearer ${token}` } })
      if (response.ok) setDrafts(await response.json())
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    loadDrafts()
    const intervalId = window.setInterval(loadDrafts, 15000)
    return () => window.clearInterval(intervalId)
  }, [loadDrafts])

  const dismiss = async (draft: AiAutoDraftItem) => {
    await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/dismiss`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ reason: reasons[draft.id]?.trim() || null }),
    })
    await loadDrafts()
  }

  const cancelAutoSend = async (draft: AiAutoDraftItem) => {
    await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/cancel-auto-send`, {
      method: 'PUT',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    await loadDrafts()
  }

  const sendNow = async (draft: AiAutoDraftItem) => {
    setSendErrors((prev) => {
      const next = { ...prev }
      delete next[draft.id]
      return next
    })
    const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/send-now`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ reason: reasons[draft.id]?.trim() || null }),
    })
    if (!response.ok) {
      let detail = 'Failed to send draft.'
      try {
        const body = await response.json()
        if (typeof body?.detail === 'string') detail = body.detail
      } catch {
        // response had no JSON body; keep the default message
      }
      setSendErrors((prev) => ({ ...prev, [draft.id]: detail }))
    }
    await loadDrafts()
  }

  const openTenant = (draft: AiAutoDraftItem) => {
    navigate(`/dashboard/tenant/${draft.tenant_id}`)
  }

  const submitRedo = async (draft: AiAutoDraftItem) => {
    const what = redoWhat.trim()
    if (!what || redoSubmitting) return
    try {
      setRedoSubmitting(true)
      const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/redo`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ what, why: redoWhy.trim() || null }),
      })
      if (response.ok) {
        setRedoOpenDraftId(null)
        setRedoWhat('')
        setRedoWhy('')
      }
      await loadDrafts()
    } finally {
      setRedoSubmitting(false)
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-4">
      <h1 className="text-2xl font-semibold text-gray-900">Pending AI Drafts</h1>
      <p className="mt-1.5 text-sm text-gray-500">
        AI-generated replies waiting for review across every tenant with auto-drafting enabled.
      </p>

      {loading && !drafts.length ? <p className="mt-4 text-sm text-gray-500">Loading...</p> : null}
      {!loading && !drafts.length ? <p className="mt-4 text-sm text-gray-500">No pending AI drafts.</p> : null}

      <div className="mt-4 space-y-3">
        {drafts.map((draft) => (
          <div key={draft.id} className="rounded-2xl border border-indigo-200 bg-white p-3.5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-700">
                  {draft.tenant_name ?? `Tenant #${draft.tenant_id}`} - {draft.channel}
                  {draft.status === 'pending_auto_send' ? ' - sending automatically soon' : ''}
                </p>
                <p className="mt-1.5 max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-6 text-gray-700">{draft.generated_text}</p>
              </div>
            </div>
            <input
              type="text"
              value={reasons[draft.id] ?? ''}
              onChange={(event) => setReasons((prev) => ({ ...prev, [draft.id]: event.target.value }))}
              placeholder="Reason for sending/dismissing (optional, logged for the redo agent)"
              className="mt-2 w-full rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-700 outline-none focus:border-cyan-300"
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => openTenant(draft)}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
              >
                Open thread
              </button>
              {draft.status === 'pending_auto_send' ? (
                <button
                  type="button"
                  onClick={() => cancelAutoSend(draft)}
                  className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100"
                >
                  Cancel auto-send
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => sendNow(draft)}
                className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
              >
                Send
              </button>
              <button
                type="button"
                onClick={() => {
                  setRedoOpenDraftId((current) => (current === draft.id ? null : draft.id))
                  setRedoWhat('')
                  setRedoWhy('')
                }}
                className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50"
              >
                Redo
              </button>
              <button
                type="button"
                onClick={() => dismiss(draft)}
                className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50"
              >
                Dismiss
              </button>
            </div>
            {redoOpenDraftId === draft.id ? (
              <div className="mt-2 space-y-1.5 rounded-lg border border-gray-200 bg-gray-50 p-2">
                <input
                  type="text"
                  value={redoWhat}
                  onChange={(event) => setRedoWhat(event.target.value)}
                  placeholder="What to change (required)"
                  className="w-full rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 outline-none focus:border-cyan-300"
                />
                <input
                  type="text"
                  value={redoWhy}
                  onChange={(event) => setRedoWhy(event.target.value)}
                  placeholder="Why (optional)"
                  className="w-full rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 outline-none focus:border-cyan-300"
                />
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => submitRedo(draft)}
                    disabled={!redoWhat.trim() || redoSubmitting}
                    className="rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {redoSubmitting ? 'Redoing...' : 'Submit redo'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setRedoOpenDraftId(null)}
                    className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-600 hover:bg-white"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : null}
            {sendErrors[draft.id] ? <p className="mt-1.5 text-xs text-red-600">{sendErrors[draft.id]}</p> : null}
          </div>
        ))}
      </div>
    </main>
  )
}
