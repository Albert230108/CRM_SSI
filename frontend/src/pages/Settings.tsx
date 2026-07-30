import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { clearDirectoryHandleForUser, getDirectoryHandleForUser, setDirectoryHandleForUser } from '../lib/fileHandleStore'
import { useLocalFolderRootPath, useRelativeTimestampsFirstPreference } from '../lib/displayPreferences'

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

type AiTemplateSection = { label: string; content: string }

type AiReplyTemplate = {
  id: number
  name: string
  guidelines: string | null
  sections: AiTemplateSection[]
  include_history: boolean
  history_message_limit: number | null
  include_beds24: boolean
  include_payments: boolean
  include_notes: boolean
}

const emptyAiTemplateForm = {
  id: null as number | null,
  name: '',
  guidelines: '',
  sections: [{ label: '', content: '' }] as AiTemplateSection[],
  include_history: false,
  history_message_limit: 20 as number | null,
  include_beds24: false,
  include_payments: false,
  include_notes: false,
}

export default function Settings() {
  const token = useAuthStore((state) => state.token)
  const userEmail = useAuthStore((state) => state.user?.email)
  const userKey = userEmail ?? 'anonymous'
  const [relativeTimestampsFirst, setRelativeTimestampsFirst] = useRelativeTimestampsFirstPreference()
  const [localFolderRootPath, setLocalFolderRootPath] = useLocalFolderRootPath()
  const [savedHandle, setSavedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [stagedHandle, setStagedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [permissionState, setPermissionState] = useState<'granted' | 'prompt' | 'denied' | null>(null)
  const [unsupported, setUnsupported] = useState(false)
  const [saving, setSaving] = useState(false)
  const [gmailAccounts, setGmailAccounts] = useState<GmailAccount[]>([])
  const [gmailMessage, setGmailMessage] = useState('')

  const [emailTemplates, setEmailTemplates] = useState<EmailTemplate[]>([])
  const [templateForm, setTemplateForm] = useState(emptyTemplateForm)
  const [savingTemplate, setSavingTemplate] = useState(false)
  const [templateMessage, setTemplateMessage] = useState('')

  const [aiTemplates, setAiTemplates] = useState<AiReplyTemplate[]>([])
  const [aiTemplateForm, setAiTemplateForm] = useState(emptyAiTemplateForm)
  const [savingAiTemplate, setSavingAiTemplate] = useState(false)
  const [aiTemplateMessage, setAiTemplateMessage] = useState('')

  const loadGmailAccounts = async () => {
    const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) setGmailAccounts(await response.json())
  }

  const loadEmailTemplates = async () => {
    const response = await fetch(`${API_BASE_URL}/api/email-templates`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) setEmailTemplates(await response.json())
  }

  const loadAiTemplates = async () => {
    const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) setAiTemplates(await response.json())
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
    loadAiTemplates()

    return () => {
      cancelled = true
    }
  }, [userKey, token])

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
    setGmailMessage('')
    const params = new URLSearchParams()
    if (accountId) params.set('account_id', String(accountId))
    const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/oauth/start${params.toString() ? `?${params.toString()}` : ''}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      setGmailMessage(data?.detail ?? 'Failed to start Google OAuth')
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
      setGmailMessage('Gmail account synced')
    }
  }

  const pollGmailSyncJob = (jobId: string) => {
    const intervalId = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/sync-status/${jobId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        const data = await response.json().catch(() => null)
        if (!response.ok || data?.status === 'done' || data?.status === 'error') {
          window.clearInterval(intervalId)
          if (data?.status === 'done') {
            await loadGmailAccounts()
            const result = data.result ?? {}
            setGmailMessage(`Synced ${result.synced_accounts ?? 0} accounts and ${result.synced_threads ?? 0} threads`)
          } else if (data?.status === 'error') {
            setGmailMessage(data?.error ? `Gmail sync failed: ${data.error}` : 'Gmail sync failed')
          }
        }
      } catch {
        window.clearInterval(intervalId)
      }
    }, 3000)
  }

  const syncAllGmailAccounts = async () => {
    const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/sync-all`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    const data = await response.json().catch(() => null)
    if (response.ok && data?.job_id) {
      setGmailMessage('Syncing Gmail accounts in the background...')
      pollGmailSyncJob(data.job_id)
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
      setGmailMessage('Gmail account disconnected')
    }
  }

  const startEditTemplate = (template: EmailTemplate) => {
    setTemplateMessage('')
    setTemplateForm({ id: template.id, name: template.name, subject: template.subject ?? '', body: template.body })
  }

  const cancelEditTemplate = () => {
    setTemplateMessage('')
    setTemplateForm(emptyTemplateForm)
  }

  const saveEmailTemplate = async (event: FormEvent) => {
    event.preventDefault()
    setTemplateMessage('')
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
        setTemplateMessage(data?.detail ?? 'Failed to save template')
        return
      }
      setTemplateForm(emptyTemplateForm)
      await loadEmailTemplates()
    } catch {
      setTemplateMessage('Failed to save template')
    } finally {
      setSavingTemplate(false)
    }
  }

  const deleteEmailTemplate = async (templateId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/email-templates/${templateId}`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      if (templateForm.id === templateId) setTemplateForm(emptyTemplateForm)
      await loadEmailTemplates()
    }
  }

  const startEditAiTemplate = (template: AiReplyTemplate) => {
    setAiTemplateMessage('')
    setAiTemplateForm({
      id: template.id,
      name: template.name,
      guidelines: template.guidelines ?? '',
      sections: template.sections.length ? template.sections : [{ label: '', content: '' }],
      include_history: template.include_history,
      history_message_limit: template.history_message_limit ?? 20,
      include_beds24: template.include_beds24,
      include_payments: template.include_payments,
      include_notes: template.include_notes,
    })
  }

  const cancelEditAiTemplate = () => {
    setAiTemplateMessage('')
    setAiTemplateForm(emptyAiTemplateForm)
  }

  const updateAiTemplateSection = (index: number, field: keyof AiTemplateSection, value: string) => {
    setAiTemplateForm((current) => ({
      ...current,
      sections: current.sections.map((section, i) => (i === index ? { ...section, [field]: value } : section)),
    }))
  }

  const addAiTemplateSection = () => {
    setAiTemplateForm((current) => ({ ...current, sections: [...current.sections, { label: '', content: '' }] }))
  }

  const removeAiTemplateSection = (index: number) => {
    setAiTemplateForm((current) => ({ ...current, sections: current.sections.filter((_, i) => i !== index) }))
  }

  const moveAiTemplateSection = (index: number, direction: -1 | 1) => {
    setAiTemplateForm((current) => {
      const targetIndex = index + direction
      if (targetIndex < 0 || targetIndex >= current.sections.length) return current
      const sections = [...current.sections]
      const [moved] = sections.splice(index, 1)
      sections.splice(targetIndex, 0, moved)
      return { ...current, sections }
    })
  }

  const saveAiTemplate = async (event: FormEvent) => {
    event.preventDefault()
    setAiTemplateMessage('')
    setSavingAiTemplate(true)
    try {
      const isEditing = aiTemplateForm.id !== null
      const response = await fetch(
        `${API_BASE_URL}/api/ai-reply-templates${isEditing ? `/${aiTemplateForm.id}` : ''}`,
        {
          method: isEditing ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({
            name: aiTemplateForm.name.trim(),
            guidelines: aiTemplateForm.guidelines.trim() || null,
            sections: aiTemplateForm.sections.filter((section) => section.label.trim() || section.content.trim()),
            include_history: aiTemplateForm.include_history,
            history_message_limit: aiTemplateForm.include_history ? aiTemplateForm.history_message_limit : null,
            include_beds24: aiTemplateForm.include_beds24,
            include_payments: aiTemplateForm.include_payments,
            include_notes: aiTemplateForm.include_notes,
          }),
        },
      )
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setAiTemplateMessage(data?.detail ?? 'Failed to save template')
        return
      }
      setAiTemplateForm(emptyAiTemplateForm)
      await loadAiTemplates()
    } catch {
      setAiTemplateMessage('Failed to save template')
    } finally {
      setSavingAiTemplate(false)
    }
  }

  const deleteAiTemplate = async (templateId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates/${templateId}`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      if (aiTemplateForm.id === templateId) setAiTemplateForm(emptyAiTemplateForm)
      await loadAiTemplates()
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
    <main className="mx-auto max-w-4xl px-6 py-4">
      <h1 className="text-2xl font-semibold text-gray-900">Settings</h1>
      <p className="text-sm text-gray-500">{userEmail ?? 'Signed in'}</p>

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
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

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
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

        {gmailMessage ? <p className="mt-2 text-sm text-gray-600">{gmailMessage}</p> : null}

        <div className="mt-3 overflow-x-auto">
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
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
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

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
        <h2 className="text-lg font-semibold text-gray-900">Email Templates</h2>
        <p className="mt-1.5 text-sm text-gray-500">
          Personal templates you can select as a starting body when using "AI Reply" to forward an email thread.
          Use placeholders below and they'll be filled in with the tenant's info: {EMAIL_TEMPLATE_PLACEHOLDERS.map((p) => `{{${p}}}`).join(', ')}
        </p>

        <div className="mt-3 space-y-2">
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
                  <button type="button" className="rounded-lg border border-rose-200 px-3 py-1 text-xs font-semibold text-rose-600" onClick={() => deleteEmailTemplate(template.id)}>Delete</button>
                </div>
              </div>
            </div>
          ))}
          {!emailTemplates.length ? <p className="text-sm text-gray-500">No templates yet.</p> : null}
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
          {templateMessage ? <p className="text-sm text-gray-600">{templateMessage}</p> : null}
        </form>
      </section>

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-3.5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Shared AI Reply Templates</h2>
            <p className="mt-1.5 text-sm text-gray-500">
              Templates used by "Draft with AI" in the reply box, shared across all users. The payload sent to Gemini
              always follows this fixed order:
            </p>
            <p className="mt-1.5 flex flex-wrap gap-2 text-xs font-semibold text-gray-600">
              <span className="rounded-full bg-gray-100 px-2 py-0.5">0. Goal &amp; Guidelines</span>
              <span className="rounded-full bg-gray-100 px-2 py-0.5">1. Template text</span>
              <span className="rounded-full bg-gray-100 px-2 py-0.5">2. Message history</span>
              <span className="rounded-full bg-gray-100 px-2 py-0.5">3. Beds24 info (booking + payments + notes)</span>
              <span className="rounded-full bg-gray-100 px-2 py-0.5">4. Your typed reply</span>
            </p>
          </div>
          <Link to="/settings/ai-tenants" className="shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50">
            Configure per tenant &rarr;
          </Link>
        </div>

        <div className="mt-3 space-y-2">
          {aiTemplates.map((template) => (
            <div key={template.id} className="rounded-xl border border-gray-200 p-2.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-900">{template.name}</p>
                  {template.guidelines ? (
                    <p className="mt-1 truncate text-xs italic text-gray-500">0. {template.guidelines}</p>
                  ) : null}
                  <p className="mt-1 text-xs text-gray-500">{template.sections.length} section{template.sections.length === 1 ? '' : 's'}</p>
                  <p className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
                    {template.include_history ? <span className="rounded-full bg-gray-100 px-2 py-0.5">History ({template.history_message_limit ?? '-'} msgs)</span> : null}
                    {template.include_beds24 ? <span className="rounded-full bg-gray-100 px-2 py-0.5">Beds24 info</span> : null}
                    {template.include_payments ? <span className="rounded-full bg-gray-100 px-2 py-0.5">Payments/charges</span> : null}
                    {template.include_notes ? <span className="rounded-full bg-gray-100 px-2 py-0.5">Tenant notes</span> : null}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button type="button" className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700" onClick={() => startEditAiTemplate(template)}>Edit</button>
                  <button type="button" className="rounded-lg border border-rose-200 px-3 py-1 text-xs font-semibold text-rose-600" onClick={() => deleteAiTemplate(template.id)}>Delete</button>
                </div>
              </div>
            </div>
          ))}
          {!aiTemplates.length ? <p className="text-sm text-gray-500">No AI templates yet.</p> : null}
        </div>

        <form onSubmit={saveAiTemplate} className="mt-3 space-y-3 rounded-xl border border-gray-200 bg-gray-50 p-3">
          <p className="text-sm font-semibold text-gray-900">{aiTemplateForm.id !== null ? 'Edit template' : 'Add template'}</p>
          <input
            type="text"
            value={aiTemplateForm.name}
            onChange={(event) => setAiTemplateForm((current) => ({ ...current, name: event.target.value }))}
            placeholder="Template name"
            required
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
          />

          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">0. Goal &amp; Guidelines</p>
            <textarea
              value={aiTemplateForm.guidelines}
              onChange={(event) => setAiTemplateForm((current) => ({ ...current, guidelines: event.target.value }))}
              placeholder="Describe this template's goal, e.g. Used for late check-in requests; keep replies under 3 sentences."
              rows={2}
              className="w-full resize-y rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
            />
            <p className="text-xs text-gray-500">
              Supports placeholders: {EMAIL_TEMPLATE_PLACEHOLDERS.map((token) => `{{${token}}}`).join(', ')}
            </p>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">1. Template text (subprompts)</p>
            {aiTemplateForm.sections.map((section, index) => (
              <div key={index} className="rounded-lg border border-gray-200 bg-white p-2.5">
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={section.label}
                    onChange={(event) => updateAiTemplateSection(index, 'label', event.target.value)}
                    placeholder="Section label, e.g. Persona"
                    className="flex-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                  />
                  <button type="button" onClick={() => moveAiTemplateSection(index, -1)} disabled={index === 0} className="rounded-lg border border-gray-300 px-2 py-1.5 text-xs text-gray-600 disabled:opacity-30">&uarr;</button>
                  <button type="button" onClick={() => moveAiTemplateSection(index, 1)} disabled={index === aiTemplateForm.sections.length - 1} className="rounded-lg border border-gray-300 px-2 py-1.5 text-xs text-gray-600 disabled:opacity-30">&darr;</button>
                  <button type="button" onClick={() => removeAiTemplateSection(index)} className="rounded-lg border border-rose-200 px-2 py-1.5 text-xs text-rose-600">Remove</button>
                </div>
                <textarea
                  value={section.content}
                  onChange={(event) => updateAiTemplateSection(index, 'content', event.target.value)}
                  placeholder="Section content, e.g. You are a friendly host responding on behalf of..."
                  rows={3}
                  className="mt-1.5 w-full resize-y rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                />
              </div>
            ))}
            <button type="button" onClick={addAiTemplateSection} className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-100">+ Add section</button>
            <p className="text-xs text-gray-500">
              Supports placeholders: {EMAIL_TEMPLATE_PLACEHOLDERS.map((token) => `{{${token}}}`).join(', ')}
            </p>
          </div>

          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">2. Message history</p>
            <label className="flex items-center gap-3 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={aiTemplateForm.include_history}
                onChange={(event) => setAiTemplateForm((current) => ({ ...current, include_history: event.target.checked }))}
                className="h-4 w-4 rounded border-gray-300"
              />
              Include conversation history, last
              <input
                type="number"
                min={1}
                value={aiTemplateForm.history_message_limit ?? ''}
                onChange={(event) => setAiTemplateForm((current) => ({ ...current, history_message_limit: event.target.value ? Number(event.target.value) : null }))}
                disabled={!aiTemplateForm.include_history}
                className="w-20 rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 outline-none disabled:cursor-not-allowed disabled:bg-gray-100"
              />
              messages
            </label>
          </div>

          <div className="space-y-1.5">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">3. Beds24 info (booking + payments + notes)</p>
            <label className="flex items-center gap-3 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={aiTemplateForm.include_beds24}
                onChange={(event) => setAiTemplateForm((current) => ({ ...current, include_beds24: event.target.checked }))}
                className="h-4 w-4 rounded border-gray-300"
              />
              Include Beds24 booking info
            </label>
            <label className="flex items-center gap-3 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={aiTemplateForm.include_payments}
                onChange={(event) => setAiTemplateForm((current) => ({ ...current, include_payments: event.target.checked }))}
                className="h-4 w-4 rounded border-gray-300"
              />
              Include payments/charges
            </label>
            <label className="flex items-center gap-3 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={aiTemplateForm.include_notes}
                onChange={(event) => setAiTemplateForm((current) => ({ ...current, include_notes: event.target.checked }))}
                className="h-4 w-4 rounded border-gray-300"
              />
              Include tenant notes
            </label>
          </div>

          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">4. Your typed reply (sent automatically when you use "Draft with AI")</p>

          <div className="flex items-center gap-2">
            <button type="submit" disabled={savingAiTemplate} className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300">
              {savingAiTemplate ? 'Saving...' : aiTemplateForm.id !== null ? 'Save changes' : 'Add template'}
            </button>
            {aiTemplateForm.id !== null ? (
              <button type="button" onClick={cancelEditAiTemplate} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700">Cancel</button>
            ) : null}
          </div>
          {aiTemplateMessage ? <p className="text-sm text-gray-600">{aiTemplateMessage}</p> : null}
        </form>
      </section>
    </main>
  )
}
