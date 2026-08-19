import { FormEvent, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { clearDirectoryHandleForUser, getDirectoryHandleForUser, setDirectoryHandleForUser } from '../lib/fileHandleStore'
import { useLocalFolderRootPath, useRelativeTimestampsFirstPreference } from '../lib/displayPreferences'
import { useToast } from '../lib/useToast'
import ToastHost from '../components/Toast'
import ConfirmDialog from '../components/ConfirmDialog'
import SettingsSidebarLayout, { SettingsTab } from '../components/settings/SettingsSidebarLayout'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type GmailAccount = {
  id: number
  email_address: string
  display_name: string | null
  google_account_id: string | null
  is_active: boolean
  last_synced_at: string | null
  last_history_id: string | null
}

type EmailTemplate = {
  id: number
  name: string
  subject: string | null
  body: string
}

const EMAIL_TEMPLATE_PLACEHOLDERS = [
  'tenant_name', 'first_name', 'last_name', 'email', 'phone', 'check_in', 'check_out',
  'num_nights', 'num_adults', 'num_children', 'room_name', 'property_name', 'booking_id',
  'booking_status', 'language', 'arrival_time', 'departure_time', 'city', 'country',
]

const emptyTemplateForm = { id: null as number | null, name: '', subject: '', body: '' }

const SETTINGS_TABS: SettingsTab[] = [
  { id: 'display', label: 'Display' },
  { id: 'gmail', label: 'Gmail' },
  { id: 'folder', label: 'Local Folder' },
  { id: 'templates', label: 'Email Templates' },
  { id: 'ai', label: 'AI Templates' },
]

export default function Settings() {
  const token = useAuthStore((state) => state.token)
  const userEmail = useAuthStore((state) => state.user?.email)
  const isAdmin = useAuthStore((state) => state.user?.is_admin)
  const userKey = userEmail ?? 'anonymous'
  const { toast, showSuccess, showError, dismiss } = useToast()
  const [activeTab, setActiveTab] = useState('display')

  const [relativeTimestampsFirst, setRelativeTimestampsFirst] = useRelativeTimestampsFirstPreference()
  const [localFolderRootPath, setLocalFolderRootPath] = useLocalFolderRootPath()
  const [savedHandle, setSavedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [stagedHandle, setStagedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [permissionState, setPermissionState] = useState<'granted' | 'prompt' | 'denied' | null>(null)
  const [unsupported, setUnsupported] = useState(false)
  const [saving, setSaving] = useState(false)
  const [gmailAccounts, setGmailAccounts] = useState<GmailAccount[]>([])
  const [gmailLoading, setGmailLoading] = useState(true)

  const [emailTemplates, setEmailTemplates] = useState<EmailTemplate[]>([])
  const [templatesLoading, setTemplatesLoading] = useState(true)
  const [templateForm, setTemplateForm] = useState(emptyTemplateForm)
  const [savingTemplate, setSavingTemplate] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<EmailTemplate | null>(null)
  const [deletingTemplate, setDeletingTemplate] = useState(false)

  const pollIntervalRef = useRef<number | null>(null)

  const loadGmailAccounts = async () => {
    setGmailLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) {
        setGmailAccounts(await response.json())
      } else {
        showError('Failed to load Gmail accounts')
      }
    } catch {
      showError('Failed to load Gmail accounts')
    } finally {
      setGmailLoading(false)
    }
  }

  const loadEmailTemplates = async () => {
    setTemplatesLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/email-templates`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) {
        setEmailTemplates(await response.json())
      } else {
        showError('Failed to load email templates')
      }
    } catch {
      showError('Failed to load email templates')
    } finally {
      setTemplatesLoading(false)
    }
  }

  useEffect(() => {
    setUnsupported(typeof window === 'undefined' || typeof window.showDirectoryPicker !== 'function')
  }, [])

  useEffect(() => {
    let cancelled = false

    const loadHandle = async () => {
      try {
        const handle = await getDirectoryHandleForUser(userKey)
        if (cancelled || !handle) return

        try {
          const perm = await handle.queryPermission({ mode: 'read' })
          if (cancelled) return

          if (perm === 'granted') {
            setSavedHandle(handle)
            setPermissionState('granted')
          } else if (perm === 'prompt') {
            setSavedHandle(handle)
            setPermissionState('prompt')
          } else {
            setPermissionState('denied')
          }
        } catch {
          if (cancelled) return
          setPermissionState('denied')
        }
      } catch {
        return
      }
    }

    setSavedHandle(null)
    setStagedHandle(null)
    setPermissionState(null)
    loadHandle()
    loadGmailAccounts()
    loadEmailTemplates()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userKey, token])

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current !== null) window.clearInterval(pollIntervalRef.current)
    }
  }, [])

  const handleStage = async () => {
    if (unsupported) return
    try {
      const dir = await window.showDirectoryPicker({ mode: 'read' })
      setStagedHandle(dir)
    } catch {
      return
    }
  }

  const handleSave = async () => {
    if (!stagedHandle) return
    try {
      setSaving(true)
      await setDirectoryHandleForUser(userKey, stagedHandle)
      setSavedHandle(stagedHandle)
      setPermissionState('granted')
      setStagedHandle(null)
    } catch {
      return
    } finally {
      setSaving(false)
    }
  }

  const handleClear = async () => {
    try {
      setSaving(true)
      await clearDirectoryHandleForUser(userKey)
      setSavedHandle(null)
      setStagedHandle(null)
      setPermissionState(null)
    } catch {
      return
    } finally {
      setSaving(false)
    }
  }

  const handleReconnect = async () => {
    if (!savedHandle) return
    try {
      const perm = await savedHandle.requestPermission({ mode: 'read' })
      setPermissionState(perm)
    } catch {
      setPermissionState('denied')
    }
  }

  const startGmailOAuth = async (accountId?: number) => {
    const params = new URLSearchParams()
    if (accountId) params.set('account_id', String(accountId))
    const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/oauth/start${params.toString() ? `?${params.toString()}` : ''}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      showError(data?.detail ?? 'Failed to start Google OAuth')
      return
    }
    window.location.assign(data.authorization_url)
  }

  const syncGmailAccount = async (accountId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/${accountId}/sync`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      await loadGmailAccounts()
      showSuccess('Gmail account synced')
    } else {
      showError('Failed to sync Gmail account')
    }
  }

  const pollGmailSyncJob = (jobId: string) => {
    if (pollIntervalRef.current !== null) window.clearInterval(pollIntervalRef.current)
    const intervalId = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/sync-status/${jobId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        const data = await response.json().catch(() => null)
        if (!response.ok || data?.status === 'done' || data?.status === 'error') {
          window.clearInterval(intervalId)
          pollIntervalRef.current = null
          if (data?.status === 'done') {
            await loadGmailAccounts()
            const result = data.result ?? {}
            showSuccess(`Synced ${result.synced_accounts ?? 0} accounts and ${result.synced_threads ?? 0} threads`)
          } else if (data?.status === 'error') {
            showError(data?.error ? `Gmail sync failed: ${data.error}` : 'Gmail sync failed')
          }
        }
      } catch {
        window.clearInterval(intervalId)
        pollIntervalRef.current = null
      }
    }, 3000)
    pollIntervalRef.current = intervalId
  }

  const syncAllGmailAccounts = async () => {
    const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/sync-all`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    const data = await response.json().catch(() => null)
    if (response.ok && data?.job_id) {
      showSuccess('Syncing Gmail accounts in the background...')
      pollGmailSyncJob(data.job_id)
    } else {
      showError('Failed to start Gmail sync')
    }
  }

  const reconnectGmailAccount = async (accountId: number) => {
    await startGmailOAuth(accountId)
  }

  const disconnectGmailAccount = async (accountId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/${accountId}/disconnect`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      await loadGmailAccounts()
      showSuccess('Gmail account disconnected')
    } else {
      showError('Failed to disconnect Gmail account')
    }
  }

  const startEditTemplate = (template: EmailTemplate) => {
    setTemplateForm({ id: template.id, name: template.name, subject: template.subject ?? '', body: template.body })
  }

  const cancelEditTemplate = () => {
    setTemplateForm(emptyTemplateForm)
  }

  const saveEmailTemplate = async (event: FormEvent) => {
    event.preventDefault()
    setSavingTemplate(true)
    try {
      const isEditing = templateForm.id !== null
      const response = await fetch(
        `${API_BASE_URL}/api/email-templates${isEditing ? `/${templateForm.id}` : ''}`,
        {
          method: isEditing ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({
            name: templateForm.name.trim(),
            subject: templateForm.subject.trim() || null,
            body: templateForm.body,
          }),
        },
      )
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        showError(data?.detail ?? 'Failed to save template')
        return
      }
      setTemplateForm(emptyTemplateForm)
      showSuccess(isEditing ? 'Template updated' : 'Template added')
      await loadEmailTemplates()
    } catch {
      showError('Failed to save template')
    } finally {
      setSavingTemplate(false)
    }
  }

  const confirmDeleteTemplate = async () => {
    if (!deleteTarget) return
    setDeletingTemplate(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/email-templates/${deleteTarget.id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) {
        if (templateForm.id === deleteTarget.id) setTemplateForm(emptyTemplateForm)
        showSuccess('Template deleted')
        setDeleteTarget(null)
        await loadEmailTemplates()
      } else {
        showError('Failed to delete template')
      }
    } finally {
      setDeletingTemplate(false)
    }
  }

  const statusDot = (tone: 'green' | 'yellow' | 'red' | 'gray') => {
    const classes = {
      green: 'bg-green-500',
      yellow: 'bg-amber-400',
      red: 'bg-red-400',
      gray: 'bg-gray-300',
    }

    return <span className={`h-2.5 w-2.5 rounded-full ${classes[tone]}`} aria-hidden="true" />
  }

  return (
    <>
      <SettingsSidebarLayout
        title="Settings"
        subtitle={userEmail ?? 'Signed in'}
        maxWidthClassName="max-w-5xl"
        tabs={SETTINGS_TABS}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        crossLink={
          isAdmin ? (
            <Link to="/admin/settings" className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50">
              Admin settings &rarr;
            </Link>
          ) : null
        }
      >
        {activeTab === 'display' ? (
          <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
            <h2 className="text-lg font-semibold text-gray-900">Display</h2>
            <p className="mt-1.5 text-sm text-gray-500">Choose the order timestamps are shown in the thread view.</p>

            <label className="mt-3 flex items-center gap-3 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={relativeTimestampsFirst}
                onChange={(event) => setRelativeTimestampsFirst(event.target.checked)}
                className="h-4 w-4 rounded border-gray-300"
              />
              Show relative time first (e.g. "4h ago (Mon 06 June 2026, 14:32)") instead of date and time first
            </label>
          </section>
        ) : null}

        {activeTab === 'gmail' ? (
          <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
            <h2 className="text-lg font-semibold text-gray-900">Shared Gmail setup</h2>
            <p className="mt-1.5 text-sm text-gray-500">
              Connect Gmail accounts once for the organization. All users use the same synced mailbox list.
            </p>

            <div className="mt-3 flex flex-wrap gap-3">
              <button type="button" className="rounded-xl bg-cyan-600 px-4 py-2.5 font-semibold text-white" onClick={() => startGmailOAuth()}>
                Connect Gmail account
              </button>
              <button type="button" className="rounded-xl border border-gray-300 px-4 py-2.5 font-semibold text-gray-900" onClick={loadGmailAccounts}>
                Refresh list
              </button>
              <button type="button" className="rounded-xl border border-gray-300 px-4 py-2.5 font-semibold text-gray-900" onClick={syncAllGmailAccounts}>
                Sync all active
              </button>
            </div>

            <div className="mt-3 overflow-x-auto">
              {gmailLoading ? (
                <p className="py-3 text-sm text-gray-500">Loading Gmail accounts...</p>
              ) : (
                <table className="min-w-full text-sm">
                  <thead className="text-left text-gray-500">
                    <tr>
                      <th className="py-1.5">Email</th><th>Display</th><th>Status</th><th>Last sync</th><th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gmailAccounts.map((account) => (
                      <tr key={account.id} className="border-t border-gray-100">
                        <td className="py-2">{account.email_address}</td>
                        <td>{account.display_name ?? '-'}</td>
                        <td>
                          <div className="flex items-center gap-2">{account.is_active ? statusDot('green') : statusDot('gray')}<span>{account.is_active ? 'Active' : 'Disconnected'}</span></div>
                        </td>
                        <td>{account.last_synced_at ? new Date(account.last_synced_at).toLocaleString() : '-'}</td>
                        <td className="space-x-2 py-2">
                          <button type="button" className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => syncGmailAccount(account.id)} disabled={!account.is_active}>Sync</button>
                          <button type="button" className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => reconnectGmailAccount(account.id)}>Reconnect</button>
                          <button type="button" className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => disconnectGmailAccount(account.id)} disabled={!account.is_active}>Disconnect</button>
                        </td>
                      </tr>
                    ))}
                    {!gmailAccounts.length ? (
                      <tr>
                        <td colSpan={5} className="py-3 text-center text-gray-400">No Gmail accounts connected yet</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        ) : null}

        {activeTab === 'folder' ? (
          <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
            <h2 className="text-lg font-semibold text-gray-900">Local Folder</h2>
            <p className="mt-1.5 text-sm text-gray-500">
              Select the root folder on your computer where tenant files are stored. This setting is saved per user and restored on each visit.
            </p>

            {unsupported ? (
              <p className="mt-3 text-sm text-gray-600">Local folder access is not supported in this browser.</p>
            ) : (
              <div className="mt-3 space-y-3">
                <div className="flex items-center gap-2 text-sm text-gray-700">
                  {savedHandle && permissionState === 'granted' ? statusDot('green') : null}
                  {savedHandle && permissionState === 'prompt' ? statusDot('yellow') : null}
                  {savedHandle && permissionState === 'denied' ? statusDot('red') : null}
                  {!savedHandle ? statusDot('gray') : null}
                  {savedHandle && permissionState === 'granted' ? `Connected - ${savedHandle.name}` : null}
                  {savedHandle && permissionState === 'prompt' ? `Permission needed - ${savedHandle.name}` : null}
                  {savedHandle && permissionState === 'denied' ? 'Access denied - choose a new folder' : null}
                  {!savedHandle ? 'No folder selected' : null}
                </div>

                {stagedHandle ? <p className="text-sm text-gray-600">Staged: {stagedHandle.name}</p> : null}

                <div className="flex flex-wrap gap-3">
                  {savedHandle && permissionState === 'granted' ? <button type="button" onClick={handleStage} disabled={saving} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60">Change folder</button> : null}
                  {savedHandle && permissionState === 'prompt' ? <button type="button" onClick={handleReconnect} disabled={saving} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60">Reconnect</button> : null}
                  {savedHandle && permissionState === 'denied' ? <button type="button" onClick={handleStage} disabled={saving} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60">Choose new folder</button> : null}
                  {!savedHandle ? <button type="button" onClick={handleStage} disabled={saving} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60">Choose folder</button> : null}
                  {stagedHandle ? (
                    <>
                      <button type="button" onClick={handleSave} disabled={saving} className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60">Save</button>
                      <button type="button" onClick={() => setStagedHandle(null)} disabled={saving} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60">Cancel</button>
                    </>
                  ) : null}
                  {savedHandle ? <button type="button" onClick={handleClear} disabled={saving} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60">Disconnect</button> : null}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700" htmlFor="local-folder-root-path">
                    Root folder path (for "Copy Explorer path")
                  </label>
                  <p className="mt-1 text-sm text-gray-500">
                    Browsers can't read the absolute disk path of the folder you selected above, and can't open File Explorer directly for security reasons. Enter the path here manually (e.g. C:\Users\you\Tenants) so the tenant tile's button can copy the full folder path - paste it into Explorer's address bar (Win+E, then Ctrl+V, Enter) to jump straight there.
                  </p>
                  <input
                    id="local-folder-root-path"
                    type="text"
                    value={localFolderRootPath}
                    onChange={(event) => setLocalFolderRootPath(event.target.value)}
                    placeholder="C:\Users\you\Tenants"
                    className="mt-1.5 w-full max-w-md rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900"
                  />
                </div>
              </div>
            )}
          </section>
        ) : null}

        {activeTab === 'templates' ? (
          <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
            <h2 className="text-lg font-semibold text-gray-900">Email Templates</h2>
            <p className="mt-1.5 text-sm text-gray-500">
              Personal templates you can select as a starting body when using "AI Reply" to forward an email thread.
              Use placeholders below and they'll be filled in with the tenant's info: {EMAIL_TEMPLATE_PLACEHOLDERS.map((p) => `{{${p}}}`).join(', ')}
            </p>

            <div className="mt-3 space-y-2">
              {templatesLoading ? (
                <p className="text-sm text-gray-500">Loading templates...</p>
              ) : (
                <>
                  {emailTemplates.map((template) => (
                    <div key={template.id} className="rounded-xl border border-gray-200 p-2.5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-gray-900">{template.name}</p>
                          {template.subject ? <p className="text-xs text-gray-500">Subject: {template.subject}</p> : null}
                          <p className="mt-1 truncate text-sm text-gray-600">{template.body}</p>
                        </div>
                        <div className="flex shrink-0 gap-2">
                          <button type="button" className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700" onClick={() => startEditTemplate(template)}>Edit</button>
                          <button type="button" className="rounded-lg border border-rose-200 px-3 py-1 text-xs font-semibold text-rose-600" onClick={() => setDeleteTarget(template)}>Delete</button>
                        </div>
                      </div>
                    </div>
                  ))}
                  {!emailTemplates.length ? <p className="text-sm text-gray-500">No templates yet.</p> : null}
                </>
              )}
            </div>

            <form onSubmit={saveEmailTemplate} className="mt-3 space-y-2 rounded-xl border border-gray-200 bg-gray-50 p-3">
              <p className="text-sm font-semibold text-gray-900">{templateForm.id !== null ? 'Edit template' : 'Add template'}</p>
              <input
                type="text"
                value={templateForm.name}
                onChange={(event) => setTemplateForm((current) => ({ ...current, name: event.target.value }))}
                placeholder="Template name"
                required
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
              />
              <input
                type="text"
                value={templateForm.subject}
                onChange={(event) => setTemplateForm((current) => ({ ...current, subject: event.target.value }))}
                placeholder="Subject (optional)"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
              />
              <textarea
                value={templateForm.body}
                onChange={(event) => setTemplateForm((current) => ({ ...current, body: event.target.value }))}
                placeholder="Body, e.g. Hi {{first_name}}, your stay at {{property_name}} runs from {{check_in}} to {{check_out}}..."
                rows={4}
                required
                className="w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
              />
              <div className="flex items-center gap-2">
                <button type="submit" disabled={savingTemplate} className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300">
                  {savingTemplate ? 'Saving...' : templateForm.id !== null ? 'Save changes' : 'Add template'}
                </button>
                {templateForm.id !== null ? (
                  <button type="button" onClick={cancelEditTemplate} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700">Cancel</button>
                ) : null}
              </div>
            </form>
          </section>
        ) : null}

        {activeTab === 'ai' ? (
          <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
            <h2 className="text-lg font-semibold text-gray-900">Shared AI Reply Templates</h2>
            <p className="mt-1.5 text-sm text-gray-500">
              Templates used by "Draft with AI" in the reply box, shared across all users. Manage the compact list, and
              edit each template's subprompts on its own draggable canvas, in a dedicated page.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link to="/settings/ai-templates" className="rounded-lg bg-cyan-600 px-3 py-2 text-xs font-semibold text-white hover:bg-cyan-700">
                Manage AI templates &rarr;
              </Link>
              <Link to="/settings/ai-tenants" className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50">
                Configure per tenant &rarr;
              </Link>
              <Link to="/settings/brain" className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100">
                Edit the AI Brain &rarr;
              </Link>
              <Link to="/settings/ai-agents" className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100">
                Planner, Drafter &amp; Checker &rarr;
              </Link>
              <Link to="/ai-runs" className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100">
                AI logs &rarr;
              </Link>
            </div>
          </section>
        ) : null}
      </SettingsSidebarLayout>

      {deleteTarget ? (
        <ConfirmDialog
          title={`Delete "${deleteTarget.name}"?`}
          description="This permanently removes this email template. This action cannot be undone."
          confirmLabel="Delete template"
          confirmingLabel="Deleting..."
          loading={deletingTemplate}
          onConfirm={confirmDeleteTemplate}
          onCancel={() => setDeleteTarget(null)}
        />
      ) : null}

      <ToastHost toast={toast} onDismiss={dismiss} />
    </>
  )
}
