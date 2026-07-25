import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type TenantSearchResult = {
  id: number
  name: string
  booking_id: string
}

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

export default function AiTenantSettings() {
  const token = useAuthStore((state) => state.token)
  const [searchQuery, setSearchQuery] = useState('')
  const [tenants, setTenants] = useState<TenantSearchResult[]>([])
  const [templates, setTemplates] = useState<AiTemplateOption[]>([])
  const [selectedTenant, setSelectedTenant] = useState<TenantSearchResult | null>(null)
  const [settings, setSettings] = useState<TenantAiSettings | null>(null)
  const [loadingSettings, setLoadingSettings] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const loadTemplates = async () => {
      const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) setTemplates(await response.json())
    }
    loadTemplates()
  }, [token])

  useEffect(() => {
    const controller = new AbortController()
    const loadTenants = async () => {
      const params = new URLSearchParams()
      if (searchQuery) params.append('search', searchQuery)
      const response = await fetch(`${API_BASE_URL}/api/tenants?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        signal: controller.signal,
      })
      if (!response.ok) return
      const data = await response.json()
      setTenants(Array.isArray(data) ? data.slice(0, 20) : [])
    }
    loadTenants().catch(() => undefined)
    return () => controller.abort()
  }, [token, searchQuery])

  const selectTenant = async (tenant: TenantSearchResult) => {
    setSelectedTenant(tenant)
    setMessage('')
    setLoadingSettings(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenant.id}/ai-settings`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      setSettings(response.ok ? await response.json() : emptySettings(tenant.id))
    } finally {
      setLoadingSettings(false)
    }
  }

  const toggleAvailableTemplate = (templateId: number) => {
    setSettings((current) => {
      if (!current) return current
      const isAvailable = current.available_template_ids.includes(templateId)
      const available_template_ids = isAvailable
        ? current.available_template_ids.filter((id) => id !== templateId)
        : [...current.available_template_ids, templateId]
      // Clearing availability for a template that's currently a default clears the default too,
      // so the UI never leaves a "default" pointing at a template no longer offered here.
      return {
        ...current,
        available_template_ids,
        default_email_template_id: !isAvailable || current.default_email_template_id !== templateId ? current.default_email_template_id : null,
        default_whatsapp_template_id: !isAvailable || current.default_whatsapp_template_id !== templateId ? current.default_whatsapp_template_id : null,
      }
    })
  }

  const setAutoDraft = (channel: 'email' | 'whatsapp', value: boolean) => {
    setSettings((current) => {
      if (!current) return current
      return {
        ...current,
        [channel === 'email' ? 'auto_draft_email' : 'auto_draft_whatsapp']: value,
        // Mirrors the server-side rule so the UI never shows an enabled auto-send toggle that a
        // save would silently revert.
        ...(value ? {} : { [channel === 'email' ? 'auto_send_email' : 'auto_send_whatsapp']: false }),
      }
    })
  }

  const setAutoSend = (channel: 'email' | 'whatsapp', value: boolean) => {
    setSettings((current) => {
      if (!current) return current
      const draftEnabled = channel === 'email' ? current.auto_draft_email : current.auto_draft_whatsapp
      if (value && !draftEnabled) return current
      return { ...current, [channel === 'email' ? 'auto_send_email' : 'auto_send_whatsapp']: value }
    })
  }

  const saveSettings = async () => {
    if (!selectedTenant || !settings) return
    setSaving(true)
    setMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${selectedTenant.id}/ai-settings`, {
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
    <main className="mx-auto max-w-4xl px-6 py-6">
      <Link to="/settings" className="text-sm text-cyan-700 hover:underline">&larr; Back to Settings</Link>
      <h1 className="mt-2 text-2xl font-semibold text-gray-900">AI Reply - Tenant Configuration</h1>
      <p className="mt-2 text-sm text-gray-500">
        Choose which shared AI templates are available for a tenant, set the default template per channel, and control
        automatic drafting/sending for that tenant.
      </p>

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="ai-tenant-search">
          Search tenants
        </label>
        <input
          id="ai-tenant-search"
          type="text"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search by tenant name..."
          className="mt-2 w-full max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
        />

        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="py-2">Tenant</th>
                <th>Booking</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tenant) => (
                <tr key={tenant.id} className="border-t border-gray-100">
                  <td className="py-2">{tenant.name}</td>
                  <td>{tenant.booking_id}</td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      onClick={() => selectTenant(tenant)}
                      className={`rounded-lg border px-3 py-1 text-xs font-semibold ${selectedTenant?.id === tenant.id ? 'border-cyan-400 bg-cyan-50 text-cyan-700' : 'border-gray-300 text-gray-700'}`}
                    >
                      {selectedTenant?.id === tenant.id ? 'Selected' : 'Configure'}
                    </button>
                  </td>
                </tr>
              ))}
              {!tenants.length ? (
                <tr>
                  <td colSpan={3} className="py-3 text-sm text-gray-500">No tenants found.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {selectedTenant ? (
        <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-gray-900">{selectedTenant.name}</h2>

          {loadingSettings || !settings ? (
            <p className="mt-3 text-sm text-gray-500">Loading...</p>
          ) : (
            <div className="mt-4 space-y-6">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Available templates</p>
                <div className="mt-2 space-y-2">
                  {templates.map((template) => (
                    <label key={template.id} className="flex items-center gap-3 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={settings.available_template_ids.includes(template.id)}
                        onChange={() => toggleAvailableTemplate(template.id)}
                        className="h-4 w-4 rounded border-gray-300"
                      />
                      {template.name}
                    </label>
                  ))}
                  {!templates.length ? <p className="text-sm text-gray-500">No shared templates yet - add one in Settings.</p> : null}
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="default-email-template">
                    Default template - Email
                  </label>
                  <select
                    id="default-email-template"
                    value={settings.default_email_template_id ?? ''}
                    onChange={(event) => setSettings((current) => current && { ...current, default_email_template_id: event.target.value ? Number(event.target.value) : null })}
                    className="mt-2 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  >
                    <option value="">No default</option>
                    {templates.filter((template) => settings.available_template_ids.includes(template.id)).map((template) => (
                      <option key={template.id} value={template.id}>{template.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="default-whatsapp-template">
                    Default template - WhatsApp
                  </label>
                  <select
                    id="default-whatsapp-template"
                    value={settings.default_whatsapp_template_id ?? ''}
                    onChange={(event) => setSettings((current) => current && { ...current, default_whatsapp_template_id: event.target.value ? Number(event.target.value) : null })}
                    className="mt-2 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  >
                    <option value="">No default</option>
                    {templates.filter((template) => settings.available_template_ids.includes(template.id)).map((template) => (
                      <option key={template.id} value={template.id}>{template.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-xl border border-gray-200 p-3">
                  <p className="text-sm font-semibold text-gray-900">Email automation</p>
                  <label className="mt-2 flex items-center gap-3 text-sm text-gray-700">
                    <input type="checkbox" checked={settings.auto_draft_email} onChange={(event) => setAutoDraft('email', event.target.checked)} className="h-4 w-4 rounded border-gray-300" />
                    Auto-draft on new email
                  </label>
                  <label className="mt-2 flex items-center gap-3 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={settings.auto_send_email}
                      disabled={!settings.auto_draft_email}
                      onChange={(event) => setAutoSend('email', event.target.checked)}
                      className="h-4 w-4 rounded border-gray-300 disabled:cursor-not-allowed"
                    />
                    Auto-send (requires auto-draft)
                  </label>
                </div>
                <div className="rounded-xl border border-gray-200 p-3">
                  <p className="text-sm font-semibold text-gray-900">WhatsApp automation</p>
                  <label className="mt-2 flex items-center gap-3 text-sm text-gray-700">
                    <input type="checkbox" checked={settings.auto_draft_whatsapp} onChange={(event) => setAutoDraft('whatsapp', event.target.checked)} className="h-4 w-4 rounded border-gray-300" />
                    Auto-draft on new WhatsApp message
                  </label>
                  <label className="mt-2 flex items-center gap-3 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={settings.auto_send_whatsapp}
                      disabled={!settings.auto_draft_whatsapp}
                      onChange={(event) => setAutoSend('whatsapp', event.target.checked)}
                      className="h-4 w-4 rounded border-gray-300 disabled:cursor-not-allowed"
                    />
                    Auto-send (requires auto-draft)
                  </label>
                </div>
              </div>

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
        </section>
      ) : null}
    </main>
  )
}
