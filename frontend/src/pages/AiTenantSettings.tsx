import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { getAiSettingsReturnHref } from '../lib/aiSettingsNavigation'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import TenantAiSettingsControls from '../components/TenantAiSettingsControls'
import Button from '../components/ui/Button'
import Select from '../components/ui/Select'
import InlineSpinner from '../components/InlineSpinner'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type TenantSearchResult = {
  id: number
  name: string
  booking_id: string
  bulk_action_locked: boolean
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
  planner_mode: 'off' | 'manual' | 'auto-draft' | 'auto-send'
  planner_profile_id: number | null
  checker_profile_id: number | null
  drafter_profile_id: number | null
  brain_writer_enabled: boolean
  brain_writer_profile_id: number | null
  action_writer_enabled: boolean
  action_writer_profile_id: number | null
  webhook_auto_run_enabled: boolean
  formatter_enabled: boolean
  formatter_profile_id: number | null
  sales_manager_profile_id: number | null
  executor_profile_id: number | null
  // null means "use the admin-configured global default" (AdminSettings.executor_default_mode).
  executor_mode: 'manual' | 'autonomous' | null
}

type AgentProfileOption = {
  id: number
  name: string
  role: 'planner' | 'checker' | 'drafter' | 'brain_writer' | 'action_writer' | 'formatter' | 'sales_manager' | 'executor' | 'memory_redo'
  is_default: boolean
}

const PAGE_SIZE = 20

// Bulk endpoints skip bulk-action-locked tenants and report how many; surface that in the message.
const skippedSuffix = (data: { skipped_locked?: number } | null): string =>
  data && data.skipped_locked ? ` (${data.skipped_locked} locked tenant${data.skipped_locked === 1 ? '' : 's'} skipped)` : ''

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
  brain_writer_enabled: false,
  brain_writer_profile_id: null,
  action_writer_enabled: false,
  action_writer_profile_id: null,
  webhook_auto_run_enabled: true,
  formatter_enabled: false,
  formatter_profile_id: null,
  sales_manager_profile_id: null,
  executor_profile_id: null,
  executor_mode: null,
})

export default function AiTenantSettings() {
  useDocumentTitle('CRM - Tenant AI Settings')
  const token = useAuthStore((state) => state.token)
  const location = useLocation()
  const [searchQuery, setSearchQuery] = useState('')
  // '' = all tenants, 'true' = locked only, 'false' = unlocked only.
  const [lockedFilter, setLockedFilter] = useState<'' | 'true' | 'false'>('')
  const [tenants, setTenants] = useState<TenantSearchResult[]>([])
  const [templates, setTemplates] = useState<AiTemplateOption[]>([])
  const [agentProfiles, setAgentProfiles] = useState<AgentProfileOption[]>([])
  const [selectedTenant, setSelectedTenant] = useState<TenantSearchResult | null>(null)
  const [settings, setSettings] = useState<TenantAiSettings | null>(null)
  const [loadingSettings, setLoadingSettings] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  const [page, setPage] = useState(0)

  const [bulkTenantIds, setBulkTenantIds] = useState<Set<number>>(new Set())
  const [bulkTemplateIds, setBulkTemplateIds] = useState<Set<number>>(new Set())
  const [bulkAction, setBulkAction] = useState<'add' | 'remove'>('add')
  const [bulkSaving, setBulkSaving] = useState(false)
  const [bulkMessage, setBulkMessage] = useState('')

  const [bulkPlannerMode, setBulkPlannerMode] = useState<TenantAiSettings['planner_mode']>('manual')
  const [bulkPlannerModeSaving, setBulkPlannerModeSaving] = useState(false)
  const [bulkPlannerModeMessage, setBulkPlannerModeMessage] = useState('')
  const [bulkBrainWriterSaving, setBulkBrainWriterSaving] = useState(false)
  const [bulkBrainWriterMessage, setBulkBrainWriterMessage] = useState('')
  const [bulkFormatterSaving, setBulkFormatterSaving] = useState(false)
  const [bulkFormatterMessage, setBulkFormatterMessage] = useState('')
  const [bulkActionWriterSaving, setBulkActionWriterSaving] = useState(false)
  const [bulkActionWriterMessage, setBulkActionWriterMessage] = useState('')
  // '' sends executor_mode=null, i.e. "use the global default".
  const [bulkExecutorMode, setBulkExecutorMode] = useState<'' | 'manual' | 'autonomous'>('manual')
  const [bulkExecutorModeSaving, setBulkExecutorModeSaving] = useState(false)
  const [bulkExecutorModeMessage, setBulkExecutorModeMessage] = useState('')
  const [bulkLockSaving, setBulkLockSaving] = useState(false)
  const [bulkLockMessage, setBulkLockMessage] = useState('')

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
      setPage(0)
      const params = new URLSearchParams()
      if (searchQuery) params.append('search', searchQuery)
      if (lockedFilter) params.append('locked', lockedFilter)
      const response = await fetch(`${API_BASE_URL}/api/tenants?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        signal: controller.signal,
      })
      if (!response.ok) return
      const data = await response.json()
      setTenants(Array.isArray(data) ? data : [])
    }
    loadTenants().catch(() => undefined)
    return () => controller.abort()
  }, [token, searchQuery, lockedFilter])

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

  const setPlannerMode = (value: TenantAiSettings['planner_mode']) => {
    setSettings((current) => {
      if (!current) return current
      // Mirrors the server-side overrides: auto-draft/auto-send imply the trigger toggles are on
      // (otherwise the mode never fires on an inbound message), and auto-draft must never leave
      // an auto-send toggle on.
      const impliesAutoDraft = value === 'auto-draft' || value === 'auto-send'
      return {
        ...current,
        planner_mode: value,
        ...(impliesAutoDraft ? { auto_draft_email: true, auto_draft_whatsapp: true } : {}),
        ...(value === 'auto-draft' ? { auto_send_email: false, auto_send_whatsapp: false } : {}),
      }
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
        (bulkAction === 'add'
          ? `Added ${data.links_added} template link(s) across ${data.tenants_affected} tenant(s).`
          : `Removed ${data.links_removed} template link(s) across ${data.tenants_affected} tenant(s).`) + skippedSuffix(data),
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

  const runBulkPlannerModeAction = async () => {
    if (!bulkTenantIds.size) return
    setBulkPlannerModeSaving(true)
    setBulkPlannerModeMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenant-ai-settings/bulk-planner-mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          tenant_ids: Array.from(bulkTenantIds),
          planner_mode: bulkPlannerMode,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setBulkPlannerModeMessage(data?.detail ?? 'Failed to run bulk action')
        return
      }
      setBulkPlannerModeMessage(`Set planner mode to "${bulkPlannerMode}" for ${data.tenants_affected} tenant(s).${skippedSuffix(data)}`)
      if (selectedTenant && bulkTenantIds.has(selectedTenant.id)) {
        await selectTenant(selectedTenant)
      }
    } finally {
      setBulkPlannerModeSaving(false)
    }
  }

  const runBulkBrainWriterAction = async (enabled: boolean) => {
    if (!bulkTenantIds.size) return
    setBulkBrainWriterSaving(true)
    setBulkBrainWriterMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenant-ai-settings/bulk-brain-writer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          tenant_ids: Array.from(bulkTenantIds),
          brain_writer_enabled: enabled,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setBulkBrainWriterMessage(data?.detail ?? 'Failed to run bulk action')
        return
      }
      setBulkBrainWriterMessage(`${enabled ? 'Activated' : 'Deactivated'} automatic brain updates for ${data.tenants_affected} tenant(s).${skippedSuffix(data)}`)
      if (selectedTenant && bulkTenantIds.has(selectedTenant.id)) {
        await selectTenant(selectedTenant)
      }
    } finally {
      setBulkBrainWriterSaving(false)
    }
  }

  const runBulkFormatterAction = async (enabled: boolean) => {
    if (!bulkTenantIds.size) return
    setBulkFormatterSaving(true)
    setBulkFormatterMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenant-ai-settings/bulk-formatter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          tenant_ids: Array.from(bulkTenantIds),
          formatter_enabled: enabled,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setBulkFormatterMessage(data?.detail ?? 'Failed to run bulk action')
        return
      }
      setBulkFormatterMessage(`${enabled ? 'Activated' : 'Deactivated'} rich formatting for ${data.tenants_affected} tenant(s).${skippedSuffix(data)}`)
      if (selectedTenant && bulkTenantIds.has(selectedTenant.id)) {
        await selectTenant(selectedTenant)
      }
    } finally {
      setBulkFormatterSaving(false)
    }
  }

  const runBulkActionWriterAction = async (enabled: boolean) => {
    if (!bulkTenantIds.size) return
    setBulkActionWriterSaving(true)
    setBulkActionWriterMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenant-ai-settings/bulk-action-writer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          tenant_ids: Array.from(bulkTenantIds),
          action_writer_enabled: enabled,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setBulkActionWriterMessage(data?.detail ?? 'Failed to run bulk action')
        return
      }
      setBulkActionWriterMessage(`${enabled ? 'Activated' : 'Deactivated'} automatic action-item updates for ${data.tenants_affected} tenant(s).${skippedSuffix(data)}`)
      if (selectedTenant && bulkTenantIds.has(selectedTenant.id)) {
        await selectTenant(selectedTenant)
      }
    } finally {
      setBulkActionWriterSaving(false)
    }
  }

  const runBulkExecutorModeAction = async () => {
    if (!bulkTenantIds.size) return
    setBulkExecutorModeSaving(true)
    setBulkExecutorModeMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenant-ai-settings/bulk-executor-mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          tenant_ids: Array.from(bulkTenantIds),
          executor_mode: bulkExecutorMode || null,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setBulkExecutorModeMessage(data?.detail ?? 'Failed to run bulk action')
        return
      }
      const label = bulkExecutorMode || 'global default'
      setBulkExecutorModeMessage(`Set executor mode to "${label}" for ${data.tenants_affected} tenant(s).${skippedSuffix(data)}`)
      if (selectedTenant && bulkTenantIds.has(selectedTenant.id)) {
        await selectTenant(selectedTenant)
      }
    } finally {
      setBulkExecutorModeSaving(false)
    }
  }

  const applyLockToLocalTenants = (ids: Set<number>, locked: boolean) => {
    setTenants((current) => current.map((tenant) => (ids.has(tenant.id) ? { ...tenant, bulk_action_locked: locked } : tenant)))
  }

  const toggleTenantLock = async (tenant: TenantSearchResult) => {
    const nextLocked = !tenant.bulk_action_locked
    // Optimistic: flip the badge immediately; the locked filter only re-applies on the next fetch.
    applyLockToLocalTenants(new Set([tenant.id]), nextLocked)
    const response = await fetch(`${API_BASE_URL}/api/tenants/${tenant.id}/bulk-action-lock`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ locked: nextLocked }),
    })
    if (!response.ok) applyLockToLocalTenants(new Set([tenant.id]), tenant.bulk_action_locked)
  }

  const runBulkLockAction = async (locked: boolean) => {
    if (!bulkTenantIds.size) return
    setBulkLockSaving(true)
    setBulkLockMessage('')
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/bulk-action-lock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ tenant_ids: Array.from(bulkTenantIds), locked }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setBulkLockMessage(data?.detail ?? 'Failed to run bulk action')
        return
      }
      applyLockToLocalTenants(bulkTenantIds, locked)
      setBulkLockMessage(`${locked ? 'Locked' : 'Unlocked'} ${data.tenants_affected} tenant(s) for bulk actions.`)
    } finally {
      setBulkLockSaving(false)
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

  const pageCount = Math.max(1, Math.ceil(tenants.length / PAGE_SIZE))
  const clampedPage = Math.min(page, pageCount - 1)
  const pagedTenants = tenants.slice(clampedPage * PAGE_SIZE, (clampedPage + 1) * PAGE_SIZE)
  const pageFullySelected = pagedTenants.length > 0 && pagedTenants.every((tenant) => bulkTenantIds.has(tenant.id))
  const pagePartiallySelected = pagedTenants.some((tenant) => bulkTenantIds.has(tenant.id)) && !pageFullySelected
  const allMatchingSelected = tenants.length > 0 && tenants.every((tenant) => bulkTenantIds.has(tenant.id))

  return (
    <main className="mx-auto animate-slide-up max-w-4xl px-6 py-4">
      <Link to={getAiSettingsReturnHref(location.search, '/settings')} className="text-sm text-brand-700 hover:underline">&larr; Back to Settings</Link>
      <h1 className="mt-1.5 text-2xl font-semibold text-gray-900">Tenant AI Settings</h1>
      <p className="mt-1.5 text-sm text-gray-500">
        Choose which shared AI templates are available for a tenant, set the default template per channel, and control
        automatic drafting/sending for that tenant.
      </p>

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
        <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="ai-tenant-search">
          Search tenants
        </label>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-md">
            <input
              id="ai-tenant-search"
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search by tenant name..."
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-9 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-brand-500"
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
          <Select
            value={lockedFilter}
            onChange={(event) => setLockedFilter(event.target.value as '' | 'true' | 'false')}
            aria-label="Filter by bulk-action lock"
            className="w-auto"
          >
            <option value="">All tenants</option>
            <option value="true">Locked only</option>
            <option value="false">Unlocked only</option>
          </Select>
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="w-8 py-1.5">
                  <input
                    type="checkbox"
                    aria-label="Select all tenants on this page for bulk actions"
                    checked={pageFullySelected}
                    ref={(el) => {
                      if (el) el.indeterminate = pagePartiallySelected
                    }}
                    onChange={(event) =>
                      setBulkTenantIds((current) => {
                        const next = new Set(current)
                        if (event.target.checked) pagedTenants.forEach((tenant) => next.add(tenant.id))
                        else pagedTenants.forEach((tenant) => next.delete(tenant.id))
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
              {pagedTenants.map((tenant) => (
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
                  <td className="py-1.5">
                    <span className="inline-flex items-center gap-1.5">
                      {tenant.name}
                      {tenant.bulk_action_locked ? (
                        <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">🔒 Locked</span>
                      ) : null}
                    </span>
                  </td>
                  <td>{tenant.booking_id}</td>
                  <td className="py-1.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => toggleTenantLock(tenant)}
                        title={tenant.bulk_action_locked ? 'Unlock: allow bulk actions to affect this tenant' : 'Lock: exclude this tenant from bulk actions'}
                        className={`rounded-lg border px-2 py-1 text-xs font-semibold ${tenant.bulk_action_locked ? 'border-amber-400 bg-amber-50 text-amber-700' : 'border-gray-300 text-gray-600'}`}
                      >
                        {tenant.bulk_action_locked ? 'Unlock' : 'Lock'}
                      </button>
                      <button
                        type="button"
                        onClick={() => selectTenant(tenant)}
                        className={`rounded-lg border px-3 py-1 text-xs font-semibold ${selectedTenant?.id === tenant.id ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-gray-300 text-gray-700'}`}
                      >
                        {selectedTenant?.id === tenant.id ? 'Selected' : 'Configure'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!pagedTenants.length ? (
                <tr>
                  <td colSpan={4} className="py-2 text-sm text-gray-500">No tenants yet.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        {tenants.length > PAGE_SIZE ? (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
            <span>
              Showing {clampedPage * PAGE_SIZE + 1}-{Math.min((clampedPage + 1) * PAGE_SIZE, tenants.length)} of {tenants.length}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={clampedPage === 0}>
                Previous
              </Button>
              <span>Page {clampedPage + 1} of {pageCount}</span>
              <Button variant="secondary" size="sm" onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))} disabled={clampedPage >= pageCount - 1}>
                Next
              </Button>
            </div>
          </div>
        ) : null}

        {pageFullySelected && tenants.length > pagedTenants.length && !allMatchingSelected ? (
          <p className="mt-2 text-xs text-gray-600">
            All {pagedTenants.length} tenants on this page are selected.{' '}
            <button
              type="button"
              onClick={() => setBulkTenantIds(new Set(tenants.map((tenant) => tenant.id)))}
              className="font-semibold text-brand-700 hover:underline"
            >
              Select all {tenants.length} tenants matching this search
            </button>
          </p>
        ) : null}
        {allMatchingSelected && tenants.length > PAGE_SIZE ? (
          <p className="mt-2 text-xs text-gray-600">
            All {tenants.length} matching tenants are selected.{' '}
            <button
              type="button"
              onClick={() => setBulkTenantIds(new Set())}
              className="font-semibold text-brand-700 hover:underline"
            >
              Clear all
            </button>
          </p>
        ) : null}

        <div className="mt-3 border-t border-gray-200 pt-3">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">
            Bulk actions ({bulkTenantIds.size} tenant{bulkTenantIds.size === 1 ? '' : 's'} selected)
          </p>
          <p className="mt-1 text-xs text-gray-500">
            Apply templates and AI modes to all selected tenants.
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
            <Select
              value={bulkAction}
              onChange={(event) => setBulkAction(event.target.value as 'add' | 'remove')}
              className="w-auto"
            >
              <option value="add">Add to selected tenants</option>
              <option value="remove">Remove from selected tenants</option>
            </Select>
            <Button onClick={runBulkAction} loading={bulkSaving} disabled={!bulkTenantIds.size || !bulkTemplateIds.size}>
              {bulkSaving ? 'Working…' : 'Apply'}
            </Button>
            {bulkMessage ? <p className="text-sm text-gray-600">{bulkMessage}</p> : null}
          </div>
        </div>

        <div className="mt-3 grid gap-3 border-t border-gray-200 pt-3 lg:grid-cols-3">
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Bulk planner mode</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Select
                value={bulkPlannerMode}
                onChange={(event) => setBulkPlannerMode(event.target.value as TenantAiSettings['planner_mode'])}
                className="w-auto"
              >
                <option value="off">Off</option>
                <option value="manual">Manual</option>
                <option value="auto-draft">Auto-draft</option>
                <option value="auto-send">Auto-send</option>
              </Select>
              <Button onClick={runBulkPlannerModeAction} loading={bulkPlannerModeSaving} disabled={!bulkTenantIds.size}>
                {bulkPlannerModeSaving ? 'Working…' : 'Apply'}
              </Button>
              {bulkPlannerModeMessage ? <p className="text-sm text-gray-600">{bulkPlannerModeMessage}</p> : null}
            </div>
          </div>

          <div className="rounded-xl border border-amber-200 bg-amber-50/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Bulk executor mode</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Select
                value={bulkExecutorMode}
                onChange={(event) => setBulkExecutorMode(event.target.value as '' | 'manual' | 'autonomous')}
                className="w-auto"
              >
                <option value="">Use global default</option>
                <option value="manual">Manual</option>
                <option value="autonomous">Autonomous</option>
              </Select>
              <Button onClick={runBulkExecutorModeAction} loading={bulkExecutorModeSaving} disabled={!bulkTenantIds.size}>
                {bulkExecutorModeSaving ? 'Working…' : 'Apply'}
              </Button>
              {bulkExecutorModeMessage ? <p className="text-sm text-gray-600">{bulkExecutorModeMessage}</p> : null}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Bulk lock / unlock</p>
            <p className="mt-1 text-xs text-gray-500">Locked tenants are skipped by every bulk action above.</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Button onClick={() => runBulkLockAction(true)} disabled={bulkLockSaving || !bulkTenantIds.size}>
                Lock
              </Button>
              <Button variant="secondary" onClick={() => runBulkLockAction(false)} disabled={bulkLockSaving || !bulkTenantIds.size}>
                Unlock
              </Button>
              {bulkLockMessage ? <p className="text-sm text-gray-600">{bulkLockMessage}</p> : null}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Bulk brain writer</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Button onClick={() => runBulkBrainWriterAction(true)} disabled={bulkBrainWriterSaving || !bulkTenantIds.size}>
                Activate
              </Button>
              <Button variant="secondary" onClick={() => runBulkBrainWriterAction(false)} disabled={bulkBrainWriterSaving || !bulkTenantIds.size}>
                Deactivate
              </Button>
              {bulkBrainWriterMessage ? <p className="text-sm text-gray-600">{bulkBrainWriterMessage}</p> : null}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Bulk action writer</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Button onClick={() => runBulkActionWriterAction(true)} disabled={bulkActionWriterSaving || !bulkTenantIds.size}>
                Activate
              </Button>
              <Button variant="secondary" onClick={() => runBulkActionWriterAction(false)} disabled={bulkActionWriterSaving || !bulkTenantIds.size}>
                Deactivate
              </Button>
              {bulkActionWriterMessage ? <p className="text-sm text-gray-600">{bulkActionWriterMessage}</p> : null}
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Bulk formatter</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Button onClick={() => runBulkFormatterAction(true)} disabled={bulkFormatterSaving || !bulkTenantIds.size}>
                Activate
              </Button>
              <Button variant="secondary" onClick={() => runBulkFormatterAction(false)} disabled={bulkFormatterSaving || !bulkTenantIds.size}>
                Deactivate
              </Button>
              {bulkFormatterMessage ? <p className="text-sm text-gray-600">{bulkFormatterMessage}</p> : null}
            </div>
          </div>
        </div>
      </section>

      {selectedTenant ? (
        <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
          <h2 className="text-lg font-semibold text-gray-900">{selectedTenant.name}</h2>

          {loadingSettings || !settings ? (
            <p className="mt-2 flex items-center gap-2 text-sm text-gray-500"><InlineSpinner size="sm" /> Loading…</p>
          ) : (
            <div className="mt-3 space-y-3">
              <TenantAiSettingsControls
                templates={templates}
                settings={settings}
                onChange={setSettings}
                idPrefix="tenant-settings"
              />

              <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Planner &amp; Checker</p>
                <p className="mt-1 text-xs text-gray-600">
                  When on, an AI planner reads the conversation and picks the template itself, then a checker
                  proof-reads the draft. Configure the profiles on the{' '}
                  <Link to="/settings/ai-agents" className="text-brand-700 hover:underline">profiles page</Link>.
                </p>
                <div className="mt-2 grid gap-3 sm:grid-cols-3">
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-mode">
                      Mode
                    </label>
                    <select
                      id="planner-mode"
                      value={settings.planner_mode}
                      onChange={(event) => setPlannerMode(event.target.value as TenantAiSettings['planner_mode'])}
                      className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500"
                    >
                      <option value="off">Off — pick templates by hand</option>
                      <option value="manual">Manual — a "Run planner" button in the reply box</option>
                      <option value="auto-draft">Auto-draft — runs on every inbound message, drafts wait in the AI Drafts tab</option>
                      <option value="auto-send">Auto-send — also sends automatically after the review window</option>
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
                      className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500 disabled:bg-gray-100"
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
                      className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500 disabled:bg-gray-100"
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
                  <Link to="/settings/ai-agents" className="text-brand-700 hover:underline">profiles page</Link>.
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
                    className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500"
                  >
                    <option value="">Use the default</option>
                    {agentProfiles.filter((profile) => profile.role === 'drafter').map((profile) => (
                      <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Sales Manager</p>
                <p className="mt-1 text-xs text-gray-600">
                  Runs between the planner and the drafter, but only when the planner asks for a quote. It
                  prices the stay and, when asked, renders a PDF quotation via the quotation manager, files it
                  in the tenant folder, and attaches it to the reply. Configure it on the{' '}
                  <Link to="/settings/ai-agents" className="text-brand-700 hover:underline">profiles page</Link>.
                </p>
                <div className="mt-2 max-w-xs">
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="sales-manager-profile">
                    Sales manager profile
                  </label>
                  <select
                    id="sales-manager-profile"
                    value={settings.sales_manager_profile_id ?? ''}
                    onChange={(event) =>
                      setSettings((current) =>
                        current ? { ...current, sales_manager_profile_id: event.target.value ? Number(event.target.value) : null } : current,
                      )
                    }
                    className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500"
                  >
                    <option value="">Use the default</option>
                    {agentProfiles.filter((profile) => profile.role === 'sales_manager').map((profile) => (
                      <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Executor</p>
                <p className="mt-1 text-xs text-gray-600">
                  The only agent that writes to Beds24. When the sales manager prepares an update or a
                  brand-new booking, the executor judges it against the rules on its profile and, if
                  approved, applies it. Configure the rules on the{' '}
                  <Link to="/settings/ai-agents" className="text-brand-700 hover:underline">profiles page</Link>.
                </p>
                <div className="mt-2 max-w-xs">
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="executor-profile">
                    Executor profile
                  </label>
                  <select
                    id="executor-profile"
                    value={settings.executor_profile_id ?? ''}
                    onChange={(event) =>
                      setSettings((current) =>
                        current ? { ...current, executor_profile_id: event.target.value ? Number(event.target.value) : null } : current,
                      )
                    }
                    className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500"
                  >
                    <option value="">Use the default</option>
                    {agentProfiles.filter((profile) => profile.role === 'executor').map((profile) => (
                      <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                    ))}
                  </select>
                </div>
                <div className="mt-2 max-w-xs">
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="executor-mode">
                    Executor mode
                  </label>
                  <select
                    id="executor-mode"
                    value={settings.executor_mode ?? ''}
                    onChange={(event) =>
                      setSettings((current) =>
                        current
                          ? { ...current, executor_mode: (event.target.value || null) as 'manual' | 'autonomous' | null }
                          : current,
                      )
                    }
                    className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500"
                  >
                    <option value="">Use the global default</option>
                    <option value="manual">Manual - only pushes to Beds24 once a human approves the draft</option>
                    <option value="autonomous">Autonomous - may validate and push to Beds24 without a human</option>
                  </select>
                </div>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Tenant Brain</p>
                <p className="mt-1 text-xs text-gray-600">
                  Independent of Planner &amp; Checker mode above: when enabled, a lightweight step
                  reviews each inbound message and, if it reveals something durable worth
                  remembering about this tenant, adds it to the Tenant Brain tab next to Notes.
                </p>
                <label className="mt-2 flex items-center gap-2 text-sm text-gray-800">
                  <input
                    type="checkbox"
                    checked={settings.brain_writer_enabled}
                    onChange={(event) =>
                      setSettings((current) => (current ? { ...current, brain_writer_enabled: event.target.checked } : current))
                    }
                  />
                  Enable automatic brain updates for this tenant
                </label>
                <div className="mt-2 max-w-xs">
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="brain-writer-profile">
                    Brain writer profile
                  </label>
                  <select
                    id="brain-writer-profile"
                    value={settings.brain_writer_profile_id ?? ''}
                    disabled={!settings.brain_writer_enabled}
                    onChange={(event) =>
                      setSettings((current) =>
                        current ? { ...current, brain_writer_profile_id: event.target.value ? Number(event.target.value) : null } : current,
                      )
                    }
                    className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500 disabled:bg-gray-100"
                  >
                    <option value="">Use the default</option>
                    {agentProfiles.filter((profile) => profile.role === 'brain_writer').map((profile) => (
                      <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Action Writer</p>
                <p className="mt-1 text-xs text-gray-600">
                  Independent of the toggles above: when enabled, a lightweight step reviews each
                  inbound or outbound message and, if a task is worth tracking, adds it directly
                  to this tenant&apos;s Actions list. If it decides an existing action needs to
                  change or be removed, that goes to Pending Suggestions for a human to approve
                  first.
                </p>
                <label className="mt-2 flex items-center gap-2 text-sm text-gray-800">
                  <input
                    type="checkbox"
                    checked={settings.action_writer_enabled}
                    onChange={(event) =>
                      setSettings((current) => (current ? { ...current, action_writer_enabled: event.target.checked } : current))
                    }
                  />
                  Enable automatic action-item updates for this tenant
                </label>
                <div className="mt-2 max-w-xs">
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="action-writer-profile">
                    Action writer profile
                  </label>
                  <select
                    id="action-writer-profile"
                    value={settings.action_writer_profile_id ?? ''}
                    disabled={!settings.action_writer_enabled}
                    onChange={(event) =>
                      setSettings((current) =>
                        current ? { ...current, action_writer_profile_id: event.target.value ? Number(event.target.value) : null } : current,
                      )
                    }
                    className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500 disabled:bg-gray-100"
                  >
                    <option value="">Use the default</option>
                    {agentProfiles.filter((profile) => profile.role === 'action_writer').map((profile) => (
                      <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Booking-webhook auto-run</p>
                <p className="mt-1 text-xs text-gray-600">
                  When on (default), a Beds24 booking update for this tenant kicks off the brain and
                  action-writer runs above, so they stay current with booking changes and not only
                  with inbound messages. It only has an effect if the Brain Writer and/or Action
                  Writer toggles above are also enabled.
                </p>
                <label className="mt-2 flex items-center gap-2 text-sm text-gray-800">
                  <input
                    type="checkbox"
                    checked={settings.webhook_auto_run_enabled}
                    onChange={(event) =>
                      setSettings((current) => (current ? { ...current, webhook_auto_run_enabled: event.target.checked } : current))
                    }
                  />
                  Run the brain / action writers on Beds24 booking updates
                </label>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50/40 p-2.5">
                <p className="text-sm font-semibold text-gray-900">Formatter</p>
                <p className="mt-1 text-xs text-gray-600">
                  Independent of the draft-generation pipeline above: when enabled, the approved plain-text reply is
                  reformatted into email HTML or WhatsApp markdown before it is sent. If formatting fails, the raw
                  draft still goes out.
                </p>
                <label className="mt-2 flex items-center gap-2 text-sm text-gray-800">
                  <input
                    type="checkbox"
                    checked={settings.formatter_enabled}
                    onChange={(event) =>
                      setSettings((current) => (current ? { ...current, formatter_enabled: event.target.checked } : current))
                    }
                  />
                  Enable rich formatting for this tenant
                </label>
                <div className="mt-2 max-w-xs">
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="formatter-profile">
                    Formatter profile
                  </label>
                  <select
                    id="formatter-profile"
                    value={settings.formatter_profile_id ?? ''}
                    disabled={!settings.formatter_enabled}
                    onChange={(event) =>
                      setSettings((current) =>
                        current ? { ...current, formatter_profile_id: event.target.value ? Number(event.target.value) : null } : current,
                      )
                    }
                    className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-brand-500 disabled:bg-gray-100"
                  >
                    <option value="">Use the default</option>
                    {agentProfiles.filter((profile) => profile.role === 'formatter').map((profile) => (
                      <option key={profile.id} value={profile.id}>{profile.name}{profile.is_default ? ' (default)' : ''}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <Button onClick={saveSettings} loading={saving}>
                  {saving ? 'Saving…' : 'Save'}
                </Button>
                {message ? <p className="text-sm text-gray-600">{message}</p> : null}
              </div>
            </div>
          )}
        </section>
      ) : null}
    </main>
  )
}
