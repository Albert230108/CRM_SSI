import { useEffect, useRef, useState } from 'react'
import AiDraftControls from './AiDraftControls'
import { useAuthStore } from '../store/authStore'
import { useDraggablePosition } from '../hooks/useDraggablePosition'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type WhatsappAccount = {
  external_account_id: string
  provider: string
  label: string
}

type AiTemplateOption = {
  id: number
  name: string
}

type TenantAiSettings = {
  planner_mode?: 'off' | 'manual' | 'auto-draft' | 'auto-send'
  available_template_ids: number[]
  default_whatsapp_template_id: number | null
}

type FirstWhatsAppMessageModalProps = {
  open: boolean
  tenantId: number
  tenantName?: string
  prefillPhone: string | null
  onClose: () => void
  onSent: () => void
}

function getErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = 'detail' in payload ? (payload as { detail?: unknown }).detail : undefined
  if (typeof detail === 'string') return detail
  return fallback
}

async function readJsonSafely(response: Response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

export default function FirstWhatsAppMessageModal({
  open,
  tenantId,
  tenantName,
  prefillPhone,
  onClose,
  onSent,
}: FirstWhatsAppMessageModalProps) {
  const token = useAuthStore((state) => state.token)
  const user = useAuthStore((state) => state.user)
  const [accounts, setAccounts] = useState<WhatsappAccount[]>([])
  const [accountsLoading, setAccountsLoading] = useState(false)
  const [externalAccountId, setExternalAccountId] = useState('')
  const [phone, setPhone] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [aiTemplates, setAiTemplates] = useState<AiTemplateOption[]>([])
  const [tenantAiSettings, setTenantAiSettings] = useState<TenantAiSettings | null>(null)
  const [selectedAiTemplateId, setSelectedAiTemplateId] = useState('')
  const [aiDraftGenerating, setAiDraftGenerating] = useState(false)
  const [plannerRunning, setPlannerRunning] = useState(false)
  const [plannerNotice, setPlannerNotice] = useState('')
  const [aiDraftError, setAiDraftError] = useState('')
  const drag = useDraggablePosition()
  const backdropMouseDownRef = useRef(false)

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined

  useEffect(() => {
    if (!open) return
    setPhone(prefillPhone ?? '')
    setMessage('')
    setError('')
    setAiDraftError('')
    setPlannerNotice('')
    setSelectedAiTemplateId('')
    setExternalAccountId(user?.default_whatsapp_account_id ?? '')

    const controller = new AbortController()
    const loadAccounts = async () => {
      try {
        setAccountsLoading(true)
        const response = await fetch(`${API_BASE_URL}/api/whatsapp/accounts`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (!response.ok) {
          const payload = await readJsonSafely(response)
          throw new Error(getErrorMessage(payload, 'Failed to load WhatsApp accounts'))
        }
        const data: WhatsappAccount[] = await readJsonSafely(response)
        const list = Array.isArray(data) ? data : []
        setAccounts(list)
        const preferred = user?.default_whatsapp_account_id
        if (preferred && list.some((account) => account.external_account_id === preferred)) setExternalAccountId(preferred)
        else if (list.length === 1) setExternalAccountId(list[0].external_account_id)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load WhatsApp accounts')
      } finally {
        setAccountsLoading(false)
      }
    }

    loadAccounts()
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tenantId, prefillPhone, token, user?.default_whatsapp_account_id])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  useEffect(() => {
    if (!open || !token) return
    let cancelled = false
    const loadAiSetup = async () => {
      const [templatesResponse, settingsResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/ai-reply-templates`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_BASE_URL}/api/tenants/${tenantId}/ai-settings`, { headers: { Authorization: `Bearer ${token}` } }),
      ])
      if (cancelled) return
      if (templatesResponse.ok) setAiTemplates(await templatesResponse.json())
      if (settingsResponse.ok) setTenantAiSettings(await settingsResponse.json())
    }
    loadAiSetup()
    return () => {
      cancelled = true
    }
  }, [open, tenantId, token])

  useEffect(() => {
    if (!open || !tenantAiSettings) return
    setSelectedAiTemplateId(tenantAiSettings.default_whatsapp_template_id ? String(tenantAiSettings.default_whatsapp_template_id) : '')
  }, [open, tenantAiSettings])

  if (!open) return null

  const aiTemplateOptions = tenantAiSettings && tenantAiSettings.available_template_ids.length
    ? aiTemplates.filter((template) => tenantAiSettings.available_template_ids.includes(template.id))
    : aiTemplates
  const plannerEnabled = (tenantAiSettings?.planner_mode ?? 'off') !== 'off'
  const canSend = Boolean(externalAccountId && phone.trim() && message.trim()) && !sending

  const handleGenerateAiDraft = async () => {
    if (!token || !selectedAiTemplateId || aiDraftGenerating) return
    try {
      setAiDraftGenerating(true)
      setAiDraftError('')
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/ai-draft`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeaders ?? {}),
        },
        body: JSON.stringify({
          channel: 'whatsapp',
          template_id: Number(selectedAiTemplateId),
          rough_draft: message.trim() || null,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(data?.detail || 'Failed to generate AI draft')
      }
      setMessage(data.generated_text)
      setSelectedAiTemplateId(String(data.template_id))
    } catch (err) {
      setAiDraftError(err instanceof Error ? err.message : 'Failed to generate AI draft')
    } finally {
      setAiDraftGenerating(false)
    }
  }

  const handleRunPlanner = async () => {
    if (!plannerEnabled || plannerRunning) return
    try {
      setPlannerRunning(true)
      setAiDraftError('')
      setPlannerNotice('')
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/ai-plan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeaders ?? {}),
        },
        body: JSON.stringify({
          channel: 'whatsapp',
          rough_draft: message.trim() || null,
          attachment_ids: [],
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(data?.detail || 'Failed to run the planner')
      }
      setPlannerNotice('Planner running - check AI Drafts.')
    } catch (err) {
      setAiDraftError(err instanceof Error ? err.message : 'Failed to run the planner')
    } finally {
      setPlannerRunning(false)
    }
  }

  const handleSend = async () => {
    if (!canSend) return
    try {
      setSending(true)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/send-first-message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeaders ?? {}),
        },
        body: JSON.stringify({
          to: phone.trim(),
          message: message.trim(),
          external_account_id: externalAccountId,
        }),
      })
      if (!response.ok) {
        const payload = await readJsonSafely(response)
        if (response.status === 422) {
          throw new Error('This number does not appear to be on WhatsApp — check the number and try again.')
        }
        throw new Error(getErrorMessage(payload, 'Failed to send WhatsApp message'))
      }
      onSent()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send WhatsApp message')
    } finally {
      setSending(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      onMouseDown={(event) => {
        backdropMouseDownRef.current = event.target === event.currentTarget
      }}
      onClick={() => {
        if (!backdropMouseDownRef.current) return
        backdropMouseDownRef.current = false
        onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="first-whatsapp-message-modal-title"
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-3xl border border-gray-200 bg-white shadow-sm"
        style={drag.style}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          className="flex cursor-move items-start justify-between gap-4 border-b border-gray-200 px-5 py-3"
          onPointerDown={drag.handlePointerDown}
        >
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-emerald-600">WhatsApp</p>
            <h2 id="first-whatsapp-message-modal-title" className="mt-1 text-2xl font-semibold text-gray-900">
              New message
            </h2>
            {tenantName ? <p className="mt-1 text-sm text-gray-500">Tenant: {tenantName}</p> : null}
            <p className="mt-1 text-sm text-gray-500">
              Sends the first message to a phone number and links the resulting chat automatically.
            </p>
          </div>
          <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={onClose} className="text-sm text-gray-500 hover:text-gray-900">
            Close
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          {error ? <p className="mb-3 text-sm text-rose-500">{error}</p> : null}

          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
                Send from
              </label>
              {accountsLoading ? (
                <p className="text-sm text-gray-500">Loading WhatsApp accounts...</p>
              ) : (
                <select
                  value={externalAccountId}
                  onChange={(event) => setExternalAccountId(event.target.value)}
                  className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-900"
                >
                  <option value="">Select a WhatsApp account</option>
                  {accounts.map((account) => (
                    <option key={account.external_account_id} value={account.external_account_id}>
                      {account.label}
                    </option>
                  ))}
                </select>
              )}
              {!accountsLoading && accounts.length === 0 ? (
                <p className="mt-1 text-xs text-rose-500">No active WhatsApp accounts are connected.</p>
              ) : null}
            </div>

            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
                Phone number
              </label>
              <input
                type="text"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="+31 6 12345678"
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-900"
              />
            </div>

            <AiDraftControls
              tenantId={tenantId}
              channel="whatsapp"
              message={message}
              selectedTemplateId={selectedAiTemplateId}
              onSelectedTemplateIdChange={setSelectedAiTemplateId}
              templates={aiTemplateOptions}
              aiDraftGenerating={aiDraftGenerating}
              plannerEnabled={plannerEnabled}
              plannerRunning={plannerRunning}
              onGenerateAiDraft={handleGenerateAiDraft}
              onRunPlanner={handleRunPlanner}
            />
            {aiDraftError ? <p className="text-xs text-rose-500">{aiDraftError}</p> : null}
            {plannerNotice ? <p className="text-xs text-amber-600">{plannerNotice}</p> : null}

            <div>
              <label className="mb-1 block text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
                Message
              </label>
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={5}
                placeholder="Type the first message..."
                className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-900"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-gray-200 px-5 py-3">
          <button type="button" onClick={onClose} className="rounded-xl px-3 py-2 text-sm text-gray-500 hover:text-gray-900">
            Cancel
          </button>
          <button
            type="button"
            disabled={!canSend}
            onClick={handleSend}
            className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {sending ? 'Sending...' : 'Send message'}
          </button>
        </div>
      </div>
    </div>
  )
}
