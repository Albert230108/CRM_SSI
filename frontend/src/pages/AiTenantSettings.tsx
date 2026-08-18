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
  planner_mode: 'off' | 'manual' | 'auto'
  planner_profile_id: number | null
  checker_profile_id: number | null
  drafter_profile_id: number | null
}

type AgentProfileOption = {
  id: number
  name: string
  role: 'planner' | 'checker' | 'drafter'
  is_default: boolean
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
  planner_mode: 'off',
  planner_profile_id: null,
  checker_profile_id: null,
  drafter_profile_id: null,
})

export default function AiTenantSettings() {
  const token = useAuthStore((state) => state.token)
  const [searchQuery, setSearchQuery] = useState('')
  const [tenants, setTenants] = useState<TenantSearchResult[]>([])
  const [templates, setTemplates] = useState<AiTemplateOption[]>([])
  const [agentProfiles, setAgentProfiles] = useState<AgentProfileOption[]>([])
  const [selectedTenant, setSelectedTenant] = useState<TenantSearchResult | null>(null)
  const [settings, setSettings] = useState<TenantAiSettings | null>(null)
  const [loadingSettings, setLoadingSettings] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  const [bulkTenantIds, setBulkTenantIds] = useState<Set<number>>(new Set())
  const [bulkTemplateIds, setBulkTemplateIds] = useState<Set<number>>(new Set())
  const [bulkAction, setBulkAction] = useState<'add' | 'remove'>('add')
  const [bulkSaving, setBulkSaving] = useState(false)
  const [bulkMessage, setBulkMessage] = useState('')

  useEffect(() => {
    const loadTemplates = async () => {
      const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) setTemplates(await response.json())
    }
    const loadAgentProfiles = async () => {
      const response = await fetch(`${API_BASE_URL}/api/ai-agent-profiles`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) setAgentProfiles(await response.json())
    }
    loadTemplates()
    loadAgentProfiles()
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

  const toggleBulkTenant = (tenantId: number) => {
    setBulkTenantIds((current) => {
      const next = new Set(current)
      if (next.has(tenantId)) next.delete(tenantId)
      else next.add(tenantId)
      return next
    })
  }

  const toggleBulkTemplate = (templateId: number) => {
    setBulkTemplateIds((current) => {
      const next = new Set(current)
      if (next.has(templateId)) next.delete(templateId)
      else next.add(templateId)
      return next
    })
  }

  const runBulkAction = async () => {
    if (!bulkTenantIds.size || !bulkTemplateIds.size) return
    setBulkSaving(true)
    setBulkMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenant-ai-settings/bulk-templates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          tenant_ids: Array.from(bulkTenantIds),
          template_ids: Array.from(bulkTemplateIds),
          action: bulkAction,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setBulkMessage(data?.detail ?? 'Failed to run bulk action')
        return
      }
      setBulkMessage(
        bulkAction === 'add'
          ? `Added ${data.links_added} template link(s) across ${data.tenants_affected} tenant(s).`
          : `Removed ${data.links_removed} template link(s) across ${data.tenants_affected} tenant(s).`,
      )
      // The selected tenant's currently-open panel may now be stale (e.g. its availability or
      // defaults changed), so reload it if it was part of this batch.
      if (selectedTenant && bulkTenantIds.has(selectedTenant.id)) {
        await selectTenant(selectedTenant)
      }
    } finally {
      setBulkSaving(false)
    }
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
    <main className="mx-auto max-w-4xl px-6 py-4">
      <Link to="/settings" className="text-sm text-cyan-700 hover:underline">&larr; Back to Settings</Link>
      <h1 className="mt-1.5 text-2xl font-semibold text-gray-900">AI Reply - Tenant Configuration</h1>
      <p className="mt-1.5 text-sm text-gray-500">
        Choose which shared AI templates are available for a tenant, set the default template per channel, and control
        automatic drafting/sending for that tenant.
      </p>

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
        <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="ai-tenant-search">
          Search tenants
        </label>
        <div className="relative mt-1.5 w-full max-w-md">
          <input
            id="ai-tenant-search"
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search by tenant name..."
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-9 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              aria-label="Clear search"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-gray-400 hover:text-gray-600"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
                <path fillRule="evenodd" d="M10 8.586 5.707 4.293a1 1 0 0 0-1.414 1.414L8.586 10l-4.293 4.293a1 1 0 1 0 1.414 1.414L10 11.414l4.293 4.293a1 1 0 0 0 1.414-1.414L11.414 10l4.293-4.293a1 1 0 0 0-1.414-1.414L10 8.586Z" clipRule="evenodd" />
              </svg>
            </button>
          )}
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="w-8 py-1.5">
                  <input
                    type="checkbox"
                    aria-label="Select all shown tenants for bulk actions"
                    checked={tenants.length > 0 && tenants.every((tenant) => bulkTenantIds.has(tenant.id))}
                    onChange={(event) =>
                      setBulkTenantIds((current) => {
                        const next = new Set(current)
                        if (event.target.checked) tenants.forEach((tenant) => next.add(tenant.id))
                        else tenants.forEach((tenant) => next.delete(tenant.id))
                        return next
                      })
                    }
                    className="h-4 w-4 rounded border-gray-300"
                  />
                </th>
                <th className="py-1.5">Tenant</th>
                <th>Booking</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tenant) => (
                <tr key={tenant.id} className="border-t border-gray-100">
                  <td className="py-1.5">
                    <input
                      type="checkbox"
                      aria-label={`Select ${tenant.name} for bulk actions`}
                      checked={bulkTenantIds.has(tenant.id)}
                      onChange={() => toggleBulkTenant(tenant.id)}
                      className="h-4 w-4 rounded border-gray-300"
                    />
                  </td>
                  <td className="py-1.5">{tenant.name}</td>
                  <td>{tenant.booking_id}</td>
                  <td className="py-1.5 text-right">
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
                  <td colSpan={4} className="py-2 text-sm text-gray-500">No tenants found.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="mt-3 border-t border-gray-200 pt-3">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">
            Bulk actions ({bulkTenantIds.size} tenant{bulkTenantIds.size === 1 ? '' : 's'} selected)
          </p>
          <p className="mt-1 text-xs text-gray-500">
            Select tenants above, pick templates below, and add or remove them from all selected tenants at once.
          </p>

          <div className="mt-2 flex flex-wrap gap-3">
            {templates.map((template) => (
              <label key={template.id} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={bulkTemplateIds.has(template.id)}
                  onChange={() => toggleBulkTemplate(template.id)}
                  className="h-4 w-4 rounded border-gray-300"
                />
                {template.name}
              </label>
            ))}
            {!templates.length ? <p className="text-sm text-gray-500">No shared templates yet - add one in Settings.</p> : null}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <select
              value={bulkAction}
              onChange={(event) => setBulkAction(event.target.value as 'add' | 'remove')}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
            >
              <option value="add">Add to selected tenants</option>
              <option value="remove">Remove from selected tenants</option>
            </select>
            <button
              type="button"
              onClick={runBulkAction}
              disabled={bulkSaving || !bulkTenantIds.size || !bulkTemplateIds.size}
              className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
            >
              {bulkSaving ? 'Working...' : 'Apply'}
            </button>
            {bulkMessage ? <p className="text-sm text-gray-600">{bulkMessage}</p> : null}
          </div>
        </div>
      </section>

      {selectedTenant ? (
        <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
          <h2 className="text-lg font-semibold text-gray-900">{selectedTenant.name}</h2>

          {loadingSettings || !settings ? (
            <p className="mt-2 text-sm text-gray-500">Loading...</p>
          ) : (
            <div className="mt-3 space-y-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Available templates</p>
                <div className="mt-1.5 space-y-1.5">
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

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="default-email-template">
                    Default template - Email
                  </label>
                  <select
                    id="default-email-template"
                    value={settings.default_email_template_id ?? ''}
                    onChange={(event) => setSettings((current) => current && { ...current, default_email_template_id: event.target.value ? Number(event.target.value) : null })}
                    className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
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
                    className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  >
                    <option value="">No default</option>
                    {templates.filter((template) => settings.available_template_ids.includes(template.id)).map((template) => (
                      <option key={template.id} value={template.id}>{template.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-gray-200 p-2.5">
                  <p className="text-sm font-semibold text-gray-900">Email automation</p>
                  <label className="mt-1.5 flex items-center gap-3 text-sm text-gray-700">
                    <input type="checkbox" checked={settings.auto_draft_email} onChange={(event) => setAutoDraft('email', event.target.checked)} className="h-4 w-4 rounded border-gray-300" />
                    Auto-draft on new email
                  </label>
                  <label className="mt-1.5 flex items-center gap-3 text-sm text-gray-700">
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
                <div className="rounded-xl border border-gray-200 p-2.5">
                  <p className="text-sm font-semibold text-gray-900">WhatsApp automation</p>
                  <label className="mt-1.5 flex items-center gap-3 text-sm text-gray-700">
                    <input type="checkbox" checked={settings.auto_draft_whatsapp} onChange={(event) => setAutoDraft('whatsapp', event.target.checked)} className="h-4 w-4 rounded border-gray-300" />
                    Auto-draft on new WhatsApp message
                  </label>
                  <label className="mt-1.5 flex items-center gap-3 text-sm text-gray-700">
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

              <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Planner &amp; Checker</p>
                <p className="mt-1 text-xs text-gray-600">
                  When on, an AI planner reads the conversation and picks the template itself, then a checker
                  proof-reads the draft. Configure the profiles on the{' '}
                  <Link to="/settings/ai-agents" className="text-cyan-700 hover:underline">profiles page</Link>.
                </p>
                <div className="mt-2 grid gap-3 sm:grid-cols-3">
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-mode">
                      Mode
                    </label>
                    <select
                      id="planner-mode"
                      value={settings.planner_mode}
                      onChange={(event) =>
                        setSettings((current) =>
                          current ? { ...current, planner_mode: event.target.value as TenantAiSettings['planner_mode'] } : current,
                        )
                      }
                      className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                    >
                      <option value="off">Off — pick templates by hand</option>
                      <option value="manual">Manual — a "Run planner" button in the reply box</option>
                      <option value="auto">Auto — also runs on every inbound message</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-profile">
                      Planner profile
                    </label>
                    <select
                      id="planner-profile"
                      value={settings.planner_profile_id ?? ''}
                      disabled={settings.planner_mode === 'off'}
                      onChange={(event) =>
                        setSettings((current) =>
                          current ? { ...current, planner_profile_id: event.target.value ? Number(event.target.value) : null } : current,
                        )
                      }
                      className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500 disabled:bg-gray-100"
                    >
                      <option value="">Use the default</option>
                      {agentProfiles.filter((profile) => profile.role === 'planner').map((profile) => (
                        <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="checker-profile">
                      Checker profile
                    </label>
                    <select
                      id="checker-profile"
                      value={settings.checker_profile_id ?? ''}
                      disabled={settings.planner_mode === 'off'}
                      onChange={(event) =>
                        setSettings((current) =>
                          current ? { ...current, checker_profile_id: event.target.value ? Number(event.target.value) : null } : current,
                        )
                      }
                      className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500 disabled:bg-gray-100"
                    >
                      <option value="">Use the default</option>
                      {agentProfiles.filter((profile) => profile.role === 'checker').map((profile) => (
                        <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Drafter</p>
                <p className="mt-1 text-xs text-gray-600">
                  Writes the reply itself. Used whenever a draft is generated for this tenant - the "Draft with
                  AI" button, an auto-draft, or the planner loop above - regardless of the Planner &amp; Checker
                  mode. Configure it on the{' '}
                  <Link to="/settings/ai-agents" className="text-cyan-700 hover:underline">profiles page</Link>.
                </p>
                <div className="mt-2 max-w-xs">
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="drafter-profile">
                    Drafter profile
                  </label>
                  <select
                    id="drafter-profile"
                    value={settings.drafter_profile_id ?? ''}
                    onChange={(event) =>
                      setSettings((current) =>
                        current ? { ...current, drafter_profile_id: event.target.value ? Number(event.target.value) : null } : current,
                      )
                    }
                    className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  >
                    <option value="">Use the default</option>
                    {agentProfiles.filter((profile) => profile.role === 'drafter').map((profile) => (
                      <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                    ))}
                  </select>
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
