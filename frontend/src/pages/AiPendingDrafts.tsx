import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { sanitizeHtml } from '../lib/sanitizeHtml'
import { whatsappMarkupToHtml } from '../lib/messageFormatting'
import Button from '../components/ui/Button'
import InlineSpinner from '../components/InlineSpinner'
import TileLoadingOverlay from '../components/TileLoadingOverlay'
import { SkeletonText } from '../components/ui/Skeleton'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type AiAutoDraftItem = {
  id: number
  tenant_id: number
  tenant_name: string | null
  email_thread_id: number | null
  open_thread_tenant_id: number | null
  channel: string
  generated_text: string
  formatted_text: string | null
  quoted_context: string | null
  status: string
  scheduled_send_at: string | null
  // A Beds24 write the sales manager prepared for this draft, run past the executor agent
  // (validated + pushed) before the reply is sent. action="update" targets booking_id's invoice
  // items; action="create" builds a brand-new booking from create_payload.
  has_pending_execution: boolean
  pending_execution: {
    action?: 'update' | 'create'
    booking_id?: string
    invoice_items?: Array<{ type?: string; description?: string; qty?: number; amount?: number; vat_rate?: number }>
    create_payload?: {
      room_id?: number
      arrival?: string
      departure?: string
      first_name?: string
      last_name?: string
      invoice_items?: Array<{ type?: string; description?: string; qty?: number; amount?: number; vat_rate?: number }>
    }
  } | null
  // Lifecycle of the prepared Beds24 write, tracked separately from `status` so it can be approved
  // in its own column: null (no action) | 'pending' | 'executed' | 'rejected' | 'failed'.
  execution_status: 'pending' | 'executed' | 'rejected' | 'failed' | null
  has_quotation: boolean
  quotation_filename: string | null
  created_at: string
}

type FinanceLine = { type: string; description: string | null; amount: string }

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
  const [diffOpenId, setDiffOpenId] = useState<number | null>(null)
  const [beforeItems, setBeforeItems] = useState<Record<number, FinanceLine[]>>({})
  // Beds24-column (execution) approval state, kept separate from the message-column state above so
  // the two approvals never share an input, error or busy flag.
  const [execErrors, setExecErrors] = useState<Record<number, string>>({})
  const [execReasons, setExecReasons] = useState<Record<number, string>>({})
  const [execBusyId, setExecBusyId] = useState<number | null>(null)

  const toggleQuoteDiff = useCallback(
    async (draft: AiAutoDraftItem) => {
      if (diffOpenId === draft.id) {
        setDiffOpenId(null)
        return
      }
      setDiffOpenId(draft.id)
      // Fetch the tenant's current finance rows once, as the "before" side of the diff.
      if (!beforeItems[draft.id]) {
        try {
          const response = await fetch(`${API_BASE_URL}/api/tenants/${draft.tenant_id}/finance`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          })
          if (response.ok) {
            const data: { charges: FinanceLine[]; payments: FinanceLine[] } = await response.json()
            setBeforeItems((prev) => ({ ...prev, [draft.id]: [...data.charges, ...data.payments] }))
          }
        } catch {
          // Best-effort: the "after" side still renders on its own if this fails.
        }
      }
    },
    [diffOpenId, beforeItems, token],
  )

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

  // Poll faster while any draft is still being generated so its spinner is replaced by the real
  // text promptly instead of waiting up to 15s for the next regular refresh.
  const anyDraftGenerating = drafts.some((draft) => draft.status === 'generating')
  useEffect(() => {
    if (!anyDraftGenerating) return
    const intervalId = window.setInterval(loadDrafts, 2000)
    return () => window.clearInterval(intervalId)
  }, [anyDraftGenerating, loadDrafts])

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
    // Route to whichever tenant currently has the thread visible (the backend re-resolves shared
    // email threads), and deep-link the specific thread so it is auto-selected on arrival.
    const tenantId = draft.open_thread_tenant_id ?? draft.tenant_id
    if (draft.channel === 'email' && draft.email_thread_id != null) {
      const params = new URLSearchParams({ channel: 'email', thread_ref: String(draft.email_thread_id) })
      navigate(`/dashboard/tenant/${tenantId}?${params}`)
      return
    }
    navigate(`/dashboard/tenant/${tenantId}`)
  }

  const renderDraftPreview = (draft: AiAutoDraftItem) => {
    if (draft.status === 'generating') {
      return (
        <div className="mt-1.5">
          <p className="flex items-center gap-1.5 text-xs font-medium text-indigo-600">
            <InlineSpinner size="sm" className="text-indigo-600" />
            Generating…
          </p>
          <SkeletonText lines={3} className="mt-1.5" />
        </div>
      )
    }
    const text = (draft.formatted_text || draft.generated_text || '').trim()
    if (!text) return null
    if (draft.formatted_text) {
      return (
        <div
          className="mt-1.5 max-h-64 overflow-y-auto break-words text-sm leading-6 text-gray-700"
          dangerouslySetInnerHTML={{ __html: draft.channel === 'email' ? sanitizeHtml(draft.formatted_text) : whatsappMarkupToHtml(draft.formatted_text) }}
        />
      )
    }
    return <p className="mt-1.5 max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-6 text-gray-700">{text}</p>
  }

  const submitRedo = async (draft: AiAutoDraftItem) => {
    const what = redoWhat.trim()
    if (!what || redoSubmitting) return
    try {
      setRedoSubmitting(true)
      const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/redo`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ what, why: redoWhy.trim() || null, current_draft: (draft.formatted_text || draft.generated_text || '').trim() || null }),
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

  // Approve + push the staged Beds24 action on its own, without sending the message reply.
  const executeNow = async (draft: AiAutoDraftItem) => {
    setExecErrors((prev) => {
      const next = { ...prev }
      delete next[draft.id]
      return next
    })
    setExecBusyId(draft.id)
    try {
      const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/execute-now`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ reason: execReasons[draft.id]?.trim() || null }),
      })
      if (!response.ok) {
        let detail = 'Failed to push the Beds24 action.'
        try {
          const body = await response.json()
          if (typeof body?.detail === 'string') detail = body.detail
        } catch {
          // response had no JSON body; keep the default message
        }
        setExecErrors((prev) => ({ ...prev, [draft.id]: detail }))
      }
      await loadDrafts()
    } finally {
      setExecBusyId(null)
    }
  }

  // Drop the staged Beds24 action without pushing it; the message draft is kept.
  const rejectExecution = async (draft: AiAutoDraftItem) => {
    setExecBusyId(draft.id)
    try {
      await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/reject-execution`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ reason: execReasons[draft.id]?.trim() || null }),
      })
      await loadDrafts()
    } finally {
      setExecBusyId(null)
    }
  }

  // Message approvals: every draft whose reply still needs a decision. A draft whose message was
  // already sent but that still carries an un-approved Beds24 action stays out of this column (its
  // message is done) and only appears in the Beds24 column.
  const messageDrafts = drafts.filter((draft) => draft.status !== 'sent')
  // Beds24 approvals: drafts with a staged action still awaiting its own approval. Require an
  // actual payload too, so a row whose execution_status drifted out of sync with an empty
  // pending_execution never renders a card the approve/reject endpoints would 409 on.
  const beds24Drafts = drafts.filter((draft) => draft.execution_status === 'pending' && draft.has_pending_execution)

  return (
    <main className="mx-auto animate-slide-up max-w-6xl px-6 py-4">
      <Link to="/settings" className="text-sm text-brand-700 hover:underline">&larr; Back to Settings</Link>
      <h1 className="mt-1.5 text-2xl font-semibold text-gray-900">Pending AI Drafts</h1>
      <p className="mt-1.5 text-sm text-gray-500">
        AI-generated replies and prepared Beds24 actions waiting for review. Message replies and
        Beds24 pushes are approved independently — approving one never triggers the other.
      </p>

      {loading && !drafts.length ? <p className="mt-4 flex items-center gap-2 text-sm text-gray-500"><InlineSpinner size="sm" /> Loading…</p> : null}
      {!loading && !drafts.length ? <p className="mt-4 text-sm text-gray-500">No pending AI drafts.</p> : null}

      <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left column — message approvals */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-700">Message approvals</h2>
          <div className="mt-3 space-y-3 stagger-list">
            {!messageDrafts.length ? (
              <p className="text-sm text-gray-400">No replies waiting for review.</p>
            ) : null}
            {messageDrafts.map((draft) => {
              const isGenerating = draft.status === 'generating'
              const redoInProgress = redoSubmitting && redoOpenDraftId === draft.id
              return (
                <div key={draft.id} className="rounded-2xl border border-indigo-200 bg-white p-3.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-700">
                        {draft.tenant_name ?? `Tenant #${draft.tenant_id}`} - {draft.channel}
                        {draft.status === 'pending_auto_send' ? ' - sending automatically soon' : ''}
                      </p>
                      {/* Warn-only link to the Beds24 side: sending the reply never pushes the action. */}
                      {draft.execution_status === 'pending' ? (
                        <p className="mt-1 text-xs font-medium text-amber-700">
                          ⚠ A Beds24 action for this draft is still awaiting approval in the Beds24 column — sending the reply now won't push it.
                        </p>
                      ) : draft.execution_status === 'rejected' ? (
                        <p className="mt-1 text-xs font-medium text-amber-700">
                          ⚠ The Beds24 action for this draft was rejected — the reply may mention a quote that wasn't pushed.
                        </p>
                      ) : draft.execution_status === 'failed' ? (
                        <p className="mt-1 text-xs font-medium text-red-600">
                          ⚠ The Beds24 push failed — review the executor run before sending.
                        </p>
                      ) : null}
                      {draft.has_quotation ? (
                        <p className="mt-1 flex items-center gap-1 text-xs text-gray-500">
                          <span aria-hidden="true">📎</span>
                          {draft.quotation_filename || 'Quotation PDF'} attached
                        </p>
                      ) : null}
                      <div className="relative">
                        {renderDraftPreview(draft)}
                        <TileLoadingOverlay active={redoInProgress} />
                      </div>
                    </div>
                  </div>
                  <input
                    type="text"
                    value={reasons[draft.id] ?? ''}
                    onChange={(event) => setReasons((prev) => ({ ...prev, [draft.id]: event.target.value }))}
                    placeholder="Reason for sending/dismissing (optional, logged for the redo agent)"
                    className="mt-2 w-full rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-700 outline-none focus:border-brand-300"
                  />
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" onClick={() => openTenant(draft)}>
                      Open thread
                    </Button>
                    {draft.status === 'pending_auto_send' ? (
                      <Button variant="secondary" size="sm" onClick={() => cancelAutoSend(draft)}>
                        Cancel auto-send
                      </Button>
                    ) : null}
                    <Button size="sm" onClick={() => sendNow(draft)} disabled={isGenerating}>
                      Send
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={isGenerating}
                      onClick={() => {
                        setRedoOpenDraftId((current) => (current === draft.id ? null : draft.id))
                        setRedoWhat('')
                        setRedoWhy('')
                      }}
                    >
                      Redo
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => dismiss(draft)}>
                      Dismiss
                    </Button>
                  </div>
                  {redoOpenDraftId === draft.id ? (
                    <div className="mt-2 space-y-1.5 rounded-lg border border-gray-200 bg-gray-50 p-2">
                      <input
                        type="text"
                        value={redoWhat}
                        onChange={(event) => setRedoWhat(event.target.value)}
                        placeholder="What to change (required)"
                        className="w-full rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 outline-none focus:border-brand-300"
                      />
                      <input
                        type="text"
                        value={redoWhy}
                        onChange={(event) => setRedoWhy(event.target.value)}
                        placeholder="Why (optional)"
                        className="w-full rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 outline-none focus:border-brand-300"
                      />
                      <div className="flex gap-1.5">
                        <Button
                          variant="ai"
                          size="sm"
                          loading={redoSubmitting}
                          disabled={!redoWhat.trim()}
                          onClick={() => submitRedo(draft)}
                        >
                          {redoSubmitting ? 'Redoing…' : 'Submit redo'}
                        </Button>
                        <Button variant="secondary" size="sm" onClick={() => setRedoOpenDraftId(null)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : null}
                  {sendErrors[draft.id] ? <p className="mt-1.5 text-xs text-red-600">{sendErrors[draft.id]}</p> : null}
                </div>
              )
            })}
          </div>
        </section>

        {/* Right column — Beds24 approvals */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Beds24 approvals</h2>
          <div className="mt-3 space-y-3 stagger-list">
            {!beds24Drafts.length ? (
              <p className="text-sm text-gray-400">No Beds24 actions waiting for approval.</p>
            ) : null}
            {beds24Drafts.map((draft) => {
              const isCreate = draft.pending_execution?.action === 'create'
              const busy = execBusyId === draft.id
              return (
                <div key={draft.id} className="rounded-2xl border border-amber-200 bg-white p-3.5">
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">
                    {draft.tenant_name ?? `Tenant #${draft.tenant_id}`} · Beds24 {isCreate ? 'new booking' : 'quote update'}
                  </p>
                  <p className="mt-1 text-xs text-gray-500">Linked to draft #{draft.id} in the message column.</p>
                  <p className="mt-1.5 text-xs font-medium text-amber-700">
                    {isCreate
                      ? 'Approving asks the executor to create a new Beds24 booking from this quote. It does not send the reply.'
                      : 'Approving asks the executor to push the updated quote to this booking in Beds24. It does not send the reply.'}
                  </p>
                  {isCreate ? null : (
                    <>
                      <button
                        type="button"
                        onClick={() => void toggleQuoteDiff(draft)}
                        className="mt-1 text-xs font-medium text-indigo-600 underline hover:text-indigo-800"
                      >
                        {diffOpenId === draft.id ? 'Hide quote changes' : 'Show quote changes'}
                      </button>
                      {diffOpenId === draft.id ? (
                        <div className="mt-2 grid grid-cols-2 gap-2 rounded-lg border border-amber-200 bg-amber-50/60 p-2 text-xs">
                          <div>
                            <p className="font-semibold uppercase tracking-wide text-gray-500">Current in CRM</p>
                            {(beforeItems[draft.id] ?? []).length === 0 ? (
                              <p className="mt-1 text-gray-400">No current finance rows.</p>
                            ) : (
                              <ul className="mt-1 space-y-0.5">
                                {(beforeItems[draft.id] ?? []).map((item, i) => (
                                  <li key={i} className={item.type === 'payment' ? 'text-emerald-700' : 'text-gray-700'}>
                                    {item.description || item.type} — €{Number(item.amount).toFixed(2)}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                          <div>
                            <p className="font-semibold uppercase tracking-wide text-gray-500">Will be sent to Beds24</p>
                            <ul className="mt-1 space-y-0.5">
                              {(draft.pending_execution?.invoice_items ?? []).map((item, i) => (
                                <li key={i} className={item.type === 'payment' ? 'text-emerald-700' : 'text-gray-700'}>
                                  {item.description || item.type} — €{((item.qty ?? 1) * (item.amount ?? 0)).toFixed(2)}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      ) : null}
                    </>
                  )}
                  <input
                    type="text"
                    value={execReasons[draft.id] ?? ''}
                    onChange={(event) => setExecReasons((prev) => ({ ...prev, [draft.id]: event.target.value }))}
                    placeholder="Reason (optional, logged on the executor run)"
                    className="mt-2 w-full rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-700 outline-none focus:border-brand-300"
                  />
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" onClick={() => openTenant(draft)}>
                      Open thread
                    </Button>
                    <Button size="sm" loading={busy} onClick={() => executeNow(draft)}>
                      Approve &amp; push
                    </Button>
                    <Button variant="ghost" size="sm" disabled={busy} onClick={() => rejectExecution(draft)}>
                      Reject
                    </Button>
                  </div>
                  {execErrors[draft.id] ? <p className="mt-1.5 text-xs text-red-600">{execErrors[draft.id]}</p> : null}
                </div>
              )
            })}
          </div>
        </section>
      </div>
    </main>
  )
}
