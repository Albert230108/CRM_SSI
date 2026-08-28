import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import TenantAiSettingsControls from './TenantAiSettingsControls'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type AiTemplateOption = {
  id: number
  name: string
}

type TenantAiSettings = {
  tenant_id: number
  available_template_ids: number[]
  default_email_template_id: number | null
  default_whatsapp_template_id: number | null
  auto_draft_email: boolean
  auto_draft_whatsapp: boolean
  auto_send_email: boolean
  auto_send_whatsapp: boolean
}

const emptySettings = (tenantId: number): TenantAiSettings => ({
  tenant_id: tenantId,
  available_template_ids: [],
  default_email_template_id: null,
  default_whatsapp_template_id: null,
  auto_draft_email: false,
  auto_draft_whatsapp: false,
  auto_send_email: false,
  auto_send_whatsapp: false,
})

type TenantAiTemplatesModalProps = {
  tenantId: number
  tenantName: string
  onClose: () => void
}

export default function TenantAiTemplatesModal({ tenantId, tenantName, onClose }: TenantAiTemplatesModalProps) {
  const token = useAuthStore((state) => state.token)
  const [templates, setTemplates] = useState<AiTemplateOption[]>([])
  const [settings, setSettings] = useState<TenantAiSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const [templatesResponse, settingsResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/ai-reply-templates`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          }),
          fetch(`${API_BASE_URL}/api/tenants/${tenantId}/ai-settings`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          }),
        ])
        if (cancelled) return
        setTemplates(templatesResponse.ok ? await templatesResponse.json() : [])
        setSettings(settingsResponse.ok ? await settingsResponse.json() : emptySettings(tenantId))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [token, tenantId])

  const saveSettings = async () => {
    if (!settings) return
    setSaving(true)
    setMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/ai-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify(settings),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setMessage(data?.detail ?? 'Failed to save AI settings')
        return
      }
      setSettings(data)
      setMessage('Saved')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-gray-200 bg-white p-3.5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-lg font-semibold text-gray-900">AI templates - {tenantName}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-full p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-600"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
              <path fillRule="evenodd" d="M10 8.586 5.707 4.293a1 1 0 0 0-1.414 1.414L8.586 10l-4.293 4.293a1 1 0 1 0 1.414 1.414L10 11.414l4.293 4.293a1 1 0 0 0 1.414-1.414L11.414 10l4.293-4.293a1 1 0 0 0-1.414-1.414L10 8.586Z" clipRule="evenodd" />
            </svg>
          </button>
        </div>

        {loading || !settings ? (
          <p className="mt-2 text-sm text-gray-500">Loading...</p>
        ) : (
          <div className="mt-3 space-y-3">
            <TenantAiSettingsControls
              templates={templates}
              settings={settings}
              onChange={setSettings}
              idPrefix="tenant-modal"
            />

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={saveSettings}
                disabled={saving}
                className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              {message ? <p className="text-sm text-gray-600">{message}</p> : null}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
