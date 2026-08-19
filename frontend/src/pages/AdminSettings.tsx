import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useToast } from '../lib/useToast'
import ToastHost from '../components/Toast'
import ConfirmDialog from '../components/ConfirmDialog'
import SettingsSidebarLayout, { SettingsTab } from '../components/settings/SettingsSidebarLayout'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type UserRow = {
  id: number
  email: string
  full_name: string | null
  phone: string | null
  is_active: boolean
  is_admin: boolean
  whatsapp_notifications_enabled: boolean
  created_at: string
}

type InviteRow = {
  id: number
  email: string | null
  full_name: string | null
  phone: string | null
  role: 'admin' | 'non-admin'
  status: 'pending' | 'completed' | 'expired' | 'revoked'
  invite_url: string | null
  expires_at: string
  used_at: string | null
  revoked_at: string | null
  created_at: string
  updated_at: string
}

type Beds24WebhookLogRow = {
  id: number
  provider: string
  received_at: string
  processed_at: string | null
  dedupe_key: string
  external_event_id: string | null
  event_type: string | null
  status: string
  booking_id: string | null
  room_id: string | null
  tenant_id: number | null
  http_status: number | null
  result_message: string | null
  error_summary: string | null
  error_traceback: string | null
  raw_payload: Record<string, unknown>
  parsed_fields: Record<string, unknown> | null
}

const logStatuses = ['', 'received', 'processed', 'failed', 'ignored', 'duplicate']

const ADMIN_TABS: SettingsTab[] = [
  { id: 'users', label: 'Users & Invites' },
  { id: 'ai', label: 'AI Settings' },
  { id: 'logs', label: 'Webhook Logs' },
  { id: 'maintenance', label: 'Maintenance' },
]

function formatJson(value: unknown) {
  return JSON.stringify(value ?? null, null, 2)
}

function statusClass(status: string) {
  switch (status) {
    case 'processed':
      return 'bg-emerald-100 text-emerald-800'
    case 'failed':
      return 'bg-red-100 text-red-800'
    case 'ignored':
      return 'bg-amber-100 text-amber-800'
    case 'duplicate':
      return 'bg-slate-200 text-slate-800'
    default:
      return 'bg-cyan-100 text-cyan-800'
  }
}

const emptyNewUser = {
  email: '',
  full_name: '',
  phone: '',
  is_admin: false as boolean,
  password: '',
  password_confirmation: '',
}

export default function AdminSettings() {
  const token = useAuthStore((state) => state.token)
  const { toast, showSuccess, showError, dismiss } = useToast()
  const [activeTab, setActiveTab] = useState('users')

  const [users, setUsers] = useState<UserRow[]>([])
  const [invites, setInvites] = useState<InviteRow[]>([])
  const [webhookLogs, setWebhookLogs] = useState<Beds24WebhookLogRow[]>([])
  const [loading, setLoading] = useState(true)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteName, setInviteName] = useState('')
  const [invitePhone, setInvitePhone] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'non-admin'>('non-admin')
  const [logStatus, setLogStatus] = useState('')
  const [logEventType, setLogEventType] = useState('')
  const [logStart, setLogStart] = useState('')
  const [logEnd, setLogEnd] = useState('')
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null)

  const [showCreateUserModal, setShowCreateUserModal] = useState(false)
  const [newUser, setNewUser] = useState(emptyNewUser)
  const [creatingUser, setCreatingUser] = useState(false)
  const [createUserError, setCreateUserError] = useState('')

  const [deleteTarget, setDeleteTarget] = useState<UserRow | null>(null)
  const [deletingUser, setDeletingUser] = useState(false)
  const [deleteUserError, setDeleteUserError] = useState('')

  const [showClearInvitesModal, setShowClearInvitesModal] = useState(false)
  const [clearingInvites, setClearingInvites] = useState(false)
  const [clearInvitesError, setClearInvitesError] = useState('')

  const [backfillingBodies, setBackfillingBodies] = useState(false)

  const [forwardToEmail, setForwardToEmail] = useState('')
  const [savingForwardToEmail, setSavingForwardToEmail] = useState(false)
  const [draftDebounceSeconds, setDraftDebounceSeconds] = useState(120)
  const [notificationWhatsappDebounceSeconds, setNotificationWhatsappDebounceSeconds] = useState(120)
  const [notificationWhatsappExternalAccountId, setNotificationWhatsappExternalAccountId] = useState('')
  const [whatsappAccounts, setWhatsappAccounts] = useState<{ external_account_id: string; provider: string; label: string }[]>([])
  const [savingNotificationWhatsappDebounce, setSavingNotificationWhatsappDebounce] = useState(false)
  const [autoSendDelaySeconds, setAutoSendDelaySeconds] = useState(300)
  const [plannerDefaultMode, setPlannerDefaultMode] = useState<'off' | 'manual' | 'auto-draft' | 'auto-send'>('off')
  const [dailyTokenCap, setDailyTokenCap] = useState(0)
  const [savingPlannerDefaults, setSavingPlannerDefaults] = useState(false)
  const [savingAiDraftTiming, setSavingAiDraftTiming] = useState(false)
  const [autoApplyTemplatesToNewTenants, setAutoApplyTemplatesToNewTenants] = useState(false)
  const [savingAutoApplyTemplates, setSavingAutoApplyTemplates] = useState(false)

  const loadLogs = async () => {
    const params = new URLSearchParams()
    params.set('limit', '50')
    if (logStatus) params.set('status', logStatus)
    if (logEventType) params.set('event_type', logEventType)
    if (logStart) params.set('start', logStart)
    if (logEnd) params.set('end', logEnd)
    const response = await fetch(`${API_BASE_URL}/api/webhooks/beds24/admin/logs?${params.toString()}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      setWebhookLogs(await response.json())
    } else {
      showError('Failed to load webhook logs')
    }
  }

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [usersResponse, invitesResponse, whatsappAccountsResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/users`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined }),
          fetch(`${API_BASE_URL}/api/admin/invites`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined }),
          fetch(`${API_BASE_URL}/api/whatsapp/accounts`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined }),
        ])
        if (usersResponse.ok) setUsers(await usersResponse.json())
        else showError('Failed to load users')
        if (invitesResponse.ok) setInvites(await invitesResponse.json())
        else showError('Failed to load invites')
        if (whatsappAccountsResponse.ok) setWhatsappAccounts(await whatsappAccountsResponse.json())
        await loadLogs()
        const adminSettingsResponse = await fetch(`${API_BASE_URL}/api/admin-settings`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (adminSettingsResponse.ok) {
          const data = await adminSettingsResponse.json()
          setForwardToEmail(data.forward_to_email ?? '')
          if (typeof data.ai_draft_debounce_seconds === 'number') setDraftDebounceSeconds(data.ai_draft_debounce_seconds)
          if (typeof data.notification_whatsapp_debounce_seconds === 'number') setNotificationWhatsappDebounceSeconds(data.notification_whatsapp_debounce_seconds)
          setNotificationWhatsappExternalAccountId(typeof data.notification_whatsapp_external_account_id === 'string' ? data.notification_whatsapp_external_account_id : '')
          if (typeof data.ai_auto_send_delay_seconds === 'number') setAutoSendDelaySeconds(data.ai_auto_send_delay_seconds)
          if (typeof data.planner_default_mode === 'string') setPlannerDefaultMode(data.planner_default_mode)
          setDailyTokenCap(typeof data.ai_daily_token_cap === 'number' ? data.ai_daily_token_cap : 0)
          if (typeof data.ai_auto_apply_templates_to_new_tenants === 'boolean') setAutoApplyTemplatesToNewTenants(data.ai_auto_apply_templates_to_new_tenants)
        } else {
          showError('Failed to load admin settings')
        }
      } finally {
        setLoading(false)
      }
    }
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  useEffect(() => {
    const refreshOnUsersUpdated = () => {
      refresh()
    }
    const onStorage = (event: StorageEvent) => {
      if (event.key === 'crmssi:users-updated') refreshOnUsersUpdated()
    }
    window.addEventListener('focus', refreshOnUsersUpdated)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener('focus', refreshOnUsersUpdated)
      window.removeEventListener('storage', onStorage)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const refresh = async () => {
    const [usersResponse, invitesResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/users`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined }),
      fetch(`${API_BASE_URL}/api/admin/invites`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined }),
    ])
    if (usersResponse.ok) setUsers(await usersResponse.json())
    if (invitesResponse.ok) setInvites(await invitesResponse.json())
    await loadLogs()
  }

  const createInvite = async (event: FormEvent) => {
    event.preventDefault()
    const response = await fetch(`${API_BASE_URL}/api/admin/invites`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ email: inviteEmail || null, full_name: inviteName || null, phone: invitePhone || null, role: inviteRole }),
    })
    const data = await response.json()
    if (!response.ok) {
      showError(data.detail ?? 'Failed to create invite')
      return
    }
    if (data.invite_url) {
      await navigator.clipboard.writeText(data.invite_url).catch(() => undefined)
      setInvites((current) => [{ ...data }, ...current.filter((invite) => invite.id !== data.id)])
      showSuccess('Invitation created and link copied')
    } else {
      showSuccess('Invitation created')
    }
    setInviteEmail('')
    setInviteName('')
    setInvitePhone('')
    setInviteRole('non-admin')
    await refresh()
  }

  const copyInvite = async (invite: InviteRow) => {
    if (!invite.invite_url) return
    await navigator.clipboard.writeText(invite.invite_url)
    showSuccess('Invite link copied')
  }

  const revokeInvite = async (inviteId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/admin/invites/${inviteId}/revoke`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      await refresh()
      showSuccess('Invite revoked')
    } else {
      showError('Failed to revoke invite')
    }
  }

  const regenerateInvite = async (inviteId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/admin/invites/${inviteId}/regenerate`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      await refresh()
      showSuccess('Invite regenerated')
    } else {
      showError('Failed to regenerate invite')
    }
  }

  const toggleActive = async (userId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/users/${userId}/toggle-active`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      await refresh()
      showSuccess('User status updated')
    } else {
      showError('Failed to update user status')
    }
  }

  const toggleWhatsappNotifications = async (userId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/users/${userId}/toggle-whatsapp-notifications`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      await refresh()
      showSuccess('WhatsApp alert setting updated')
    } else {
      showError('Failed to update WhatsApp alert setting')
    }
  }

  const sendReset = async (userId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/users/${userId}/password-reset`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    const data = await response.json()
    if (response.ok) showSuccess(`Password reset link created: ${data.reset_url}`)
    else showError(data.detail ?? 'Failed to create reset link')
  }

  const applyLogFilters = async (event: FormEvent) => {
    event.preventDefault()
    await loadLogs()
  }

  const createUser = async (event: FormEvent) => {
    event.preventDefault()
    setCreateUserError('')
    if (newUser.password !== newUser.password_confirmation) {
      setCreateUserError('Passwords do not match')
      return
    }
    setCreatingUser(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          email: newUser.email,
          full_name: newUser.full_name || null,
          phone: newUser.phone || null,
          is_admin: newUser.is_admin,
          password: newUser.password,
          password_confirmation: newUser.password_confirmation,
        }),
      })
      const data = await response.json()
      if (!response.ok) {
        setCreateUserError(typeof data.detail === 'string' ? data.detail : 'Failed to create user')
        setNewUser((current) => ({ ...current, password: '', password_confirmation: '' }))
        return
      }
      setShowCreateUserModal(false)
      setNewUser(emptyNewUser)
      showSuccess(`User ${data.email} created`)
      await refresh()
    } finally {
      setCreatingUser(false)
    }
  }

  const confirmDeleteUser = async () => {
    if (!deleteTarget) return
    setDeleteUserError('')
    setDeletingUser(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/users/${deleteTarget.id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      const data = await response.json()
      if (!response.ok) {
        setDeleteUserError(typeof data.detail === 'string' ? data.detail : 'Failed to delete user')
        return
      }
      showSuccess(`User ${deleteTarget.email} deleted`)
      setDeleteTarget(null)
      await refresh()
    } finally {
      setDeletingUser(false)
    }
  }

  const backfillEmailBodies = async () => {
    setBackfillingBodies(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/backfill-bodies`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      const data = await response.json()
      if (!response.ok) {
        showError(typeof data.detail === 'string' ? data.detail : 'Failed to backfill email bodies')
        return
      }
      showSuccess(`Scanned ${data.scanned} synced email(s), updated ${data.updated}.`)
    } catch {
      showError('Failed to backfill email bodies')
    } finally {
      setBackfillingBodies(false)
    }
  }

  const saveForwardToEmail = async (event: FormEvent) => {
    event.preventDefault()
    setSavingForwardToEmail(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ forward_to_email: forwardToEmail.trim() || null }),
      })
      const data = await response.json()
      if (!response.ok) {
        showError(typeof data.detail === 'string' ? data.detail : 'Failed to save forwarding address')
        return
      }
      setForwardToEmail(data.forward_to_email ?? '')
      showSuccess('Forwarding address saved')
    } catch {
      showError('Failed to save forwarding address')
    } finally {
      setSavingForwardToEmail(false)
    }
  }

  const saveAiDraftTiming = async (event: FormEvent) => {
    event.preventDefault()
    setSavingAiDraftTiming(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ ai_draft_debounce_seconds: draftDebounceSeconds, ai_auto_send_delay_seconds: autoSendDelaySeconds }),
      })
      const data = await response.json()
      if (!response.ok) {
        showError(typeof data.detail === 'string' ? data.detail : 'Failed to save AI draft timing')
        return
      }
      setDraftDebounceSeconds(data.ai_draft_debounce_seconds)
      setAutoSendDelaySeconds(data.ai_auto_send_delay_seconds)
      showSuccess('AI draft timing saved')
    } catch {
      showError('Failed to save AI draft timing')
    } finally {
      setSavingAiDraftTiming(false)
    }
  }

  const saveNotificationWhatsappDebounce = async (event: FormEvent) => {
    event.preventDefault()
    setSavingNotificationWhatsappDebounce(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          notification_whatsapp_debounce_seconds: notificationWhatsappDebounceSeconds,
          notification_whatsapp_external_account_id: notificationWhatsappExternalAccountId || null,
          clear_notification_whatsapp_external_account_id: !notificationWhatsappExternalAccountId,
        }),
      })
      const data = await response.json()
      if (!response.ok) {
        showError(typeof data.detail === 'string' ? data.detail : 'Failed to save WhatsApp notification timing')
        return
      }
      setNotificationWhatsappDebounceSeconds(data.notification_whatsapp_debounce_seconds)
      setNotificationWhatsappExternalAccountId(typeof data.notification_whatsapp_external_account_id === 'string' ? data.notification_whatsapp_external_account_id : '')
      showSuccess('WhatsApp notification timing saved')
    } catch {
      showError('Failed to save WhatsApp notification timing')
    } finally {
      setSavingNotificationWhatsappDebounce(false)
    }
  }

  const savePlannerDefaults = async (event: FormEvent) => {
    event.preventDefault()
    setSavingPlannerDefaults(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        // 0 is how the cap is cleared: a null would be indistinguishable from "not in this
        // partial update", which is how every other field on this page signals "leave alone".
        body: JSON.stringify({ planner_default_mode: plannerDefaultMode, ai_daily_token_cap: dailyTokenCap }),
      })
      const data = await response.json()
      if (!response.ok) {
        showError(typeof data.detail === 'string' ? data.detail : 'Failed to save planner defaults')
        return
      }
      setPlannerDefaultMode(data.planner_default_mode)
      setDailyTokenCap(data.ai_daily_token_cap ?? 0)
      showSuccess('Planner defaults saved')
    } catch {
      showError('Failed to save planner defaults')
    } finally {
      setSavingPlannerDefaults(false)
    }
  }

  const saveAutoApplyTemplates = async (nextValue: boolean) => {
    setSavingAutoApplyTemplates(true)
    const previousValue = autoApplyTemplatesToNewTenants
    setAutoApplyTemplatesToNewTenants(nextValue)
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ ai_auto_apply_templates_to_new_tenants: nextValue }),
      })
      const data = await response.json()
      if (!response.ok) {
        setAutoApplyTemplatesToNewTenants(previousValue)
        showError(typeof data.detail === 'string' ? data.detail : 'Failed to save')
        return
      }
      setAutoApplyTemplatesToNewTenants(data.ai_auto_apply_templates_to_new_tenants)
      showSuccess('Saved')
    } catch {
      setAutoApplyTemplatesToNewTenants(previousValue)
      showError('Failed to save')
    } finally {
      setSavingAutoApplyTemplates(false)
    }
  }

  const confirmClearInvites = async () => {
    setClearInvitesError('')
    setClearingInvites(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/invites/clear`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      const data = await response.json()
      if (!response.ok) {
        setClearInvitesError(typeof data.detail === 'string' ? data.detail : 'Failed to clear invites')
        return
      }
      setShowClearInvitesModal(false)
      showSuccess(`Cleared ${data.revoked_count} pending invite link(s)`)
      await refresh()
    } finally {
      setClearingInvites(false)
    }
  }

  return (
    <>
      <SettingsSidebarLayout
        title="Admin Settings"
        subtitle="User management, invite onboarding, password resets, and Beds24 webhook logs."
        tabs={ADMIN_TABS}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        crossLink={
          <Link to="/settings" className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50">
            &larr; Back to Settings
          </Link>
        }
      >
        {activeTab === 'users' ? (
          <>
            <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-gray-900">Users</h2>
                <button
                  type="button"
                  className="rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-cyan-700"
                  onClick={() => {
                    setCreateUserError('')
                    setNewUser(emptyNewUser)
                    setShowCreateUserModal(true)
                  }}
                >
                  Create user
                </button>
              </div>
              <div className="mt-3 overflow-x-auto">
                {loading ? (
                  <p className="py-3 text-sm text-gray-500">Loading users...</p>
                ) : (
                  <table className="min-w-full text-sm">
                    <thead className="text-left text-gray-500">
                      <tr>
                        <th className="py-1.5">Name</th><th>Email</th><th>Phone</th><th>Status</th><th>Role</th><th>WA Alerts</th><th>Created</th><th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="py-3 text-center text-gray-400">No users yet</td>
                        </tr>
                      ) : (
                        users.map((user) => (
                          <tr key={user.id} className="border-t border-gray-100">
                            <td className="py-2">{user.full_name ?? '-'}</td>
                            <td>{user.email}</td>
                            <td>{user.phone ?? '-'}</td>
                            <td>{user.is_active ? 'Active' : 'Inactive'}</td>
                            <td>{user.is_admin ? 'Admin' : 'User'}</td>
                            <td>{user.whatsapp_notifications_enabled ? 'On' : 'Off'}</td>
                            <td>{new Date(user.created_at).toLocaleString()}</td>
                            <td className="space-x-2 py-2">
                              <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => toggleActive(user.id)} type="button">Toggle active</button>
                              <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => toggleWhatsappNotifications(user.id)} type="button">Toggle WA alerts</button>
                              <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => sendReset(user.id)} type="button">Send password reset</button>
                              <button
                                className="rounded-lg border border-rose-300 px-3 py-1 text-rose-700 hover:bg-rose-50"
                                onClick={() => {
                                  setDeleteUserError('')
                                  setDeleteTarget(user)
                                }}
                                type="button"
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
              <h2 className="text-lg font-semibold text-gray-900">Generate invite link</h2>
              <form className="mt-3 grid gap-3 md:grid-cols-5" onSubmit={createInvite}>
                <input className="rounded-xl border border-gray-300 px-4 py-2.5" placeholder="Email (optional)" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} />
                <input className="rounded-xl border border-gray-300 px-4 py-2.5" placeholder="Full name" value={inviteName} onChange={(e) => setInviteName(e.target.value)} />
                <input className="rounded-xl border border-gray-300 px-4 py-2.5" placeholder="Phone" value={invitePhone} onChange={(e) => setInvitePhone(e.target.value)} />
                <select className="rounded-xl border border-gray-300 px-4 py-2.5" value={inviteRole} onChange={(e) => setInviteRole(e.target.value as 'admin' | 'non-admin')}>
                  <option value="non-admin">Non-admin</option>
                  <option value="admin">Admin</option>
                </select>
                <button className="rounded-xl bg-cyan-600 px-4 py-2.5 font-semibold text-white">Generate invite link</button>
              </form>
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-gray-900">Invite management</h2>
                <button
                  type="button"
                  className="rounded-lg border border-rose-300 px-3 py-1.5 text-sm font-medium text-rose-700 hover:bg-rose-50"
                  onClick={() => {
                    setClearInvitesError('')
                    setShowClearInvitesModal(true)
                  }}
                >
                  Clear all pending invite links
                </button>
              </div>
              <div className="mt-3 overflow-x-auto">
                {loading ? (
                  <p className="py-3 text-sm text-gray-500">Loading invites...</p>
                ) : (
                  <table className="min-w-full text-sm">
                    <thead className="text-left text-gray-500">
                      <tr>
                        <th className="py-1.5">Email</th><th>Name</th><th>Phone</th><th>Role</th><th>Status</th><th>Expires</th><th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {invites.map((invite) => (
                        <tr key={invite.id} className="border-t border-gray-100">
                          <td className="py-2">{invite.email ?? '-'}</td>
                          <td>{invite.full_name ?? '-'}</td>
                          <td>{invite.phone ?? '-'}</td>
                          <td>{invite.role}</td>
                          <td>{invite.status}</td>
                          <td>{new Date(invite.expires_at).toLocaleString()}</td>
                          <td className="space-x-2 py-2">
                            <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => copyInvite(invite)} type="button" disabled={!invite.invite_url}>Copy link</button>
                            <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => revokeInvite(invite.id)} type="button" disabled={invite.status === 'revoked' || invite.status === 'completed'}>Revoke</button>
                            <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => regenerateInvite(invite.id)} type="button" disabled={invite.status === 'completed'}>Regenerate</button>
                          </td>
                        </tr>
                      ))}
                      {!invites.length ? (
                        <tr>
                          <td colSpan={7} className="py-3 text-center text-gray-400">No invites yet</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                )}
              </div>
            </section>
          </>
        ) : null}

        {activeTab === 'ai' ? (
          <>
            <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
              <h2 className="text-lg font-semibold text-gray-900">AI Reply forwarding address</h2>
              <p className="mt-1 text-sm text-gray-500">
                When a user clicks "AI Reply" on an email thread, the thread is forwarded to this address for AI drafting.
              </p>
              <form onSubmit={saveForwardToEmail} className="mt-3 flex max-w-lg items-center gap-3">
                <input
                  type="email"
                  value={forwardToEmail}
                  onChange={(event) => setForwardToEmail(event.target.value)}
                  placeholder="ai-drafts@example.com"
                  className="flex-1 rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                />
                <button
                  type="submit"
                  disabled={savingForwardToEmail}
                  className="shrink-0 rounded-xl bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
                >
                  {savingForwardToEmail ? 'Saving...' : 'Save'}
                </button>
              </form>
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
              <h2 className="text-lg font-semibold text-gray-900">AI Draft Timing</h2>
              <p className="mt-1 text-sm text-gray-500">
                Controls the "Draft with AI" auto-draft/auto-send pipeline: how long a conversation must go quiet before an
                auto-draft is generated, and how long a scheduled auto-send waits before actually sending, giving staff a
                window to intervene.
              </p>
              <form onSubmit={saveAiDraftTiming} className="mt-3 flex max-w-lg flex-wrap items-end gap-4">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="ai-draft-debounce-seconds">
                    Draft debounce (seconds)
                  </label>
                  <input
                    id="ai-draft-debounce-seconds"
                    type="number"
                    min={1}
                    value={draftDebounceSeconds}
                    onChange={(event) => setDraftDebounceSeconds(Number(event.target.value))}
                    className="mt-1.5 w-32 rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="ai-auto-send-delay-seconds">
                    Auto-send delay (seconds)
                  </label>
                  <input
                    id="ai-auto-send-delay-seconds"
                    type="number"
                    min={1}
                    value={autoSendDelaySeconds}
                    onChange={(event) => setAutoSendDelaySeconds(Number(event.target.value))}
                    className="mt-1.5 w-32 rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  />
                </div>
                <button
                  type="submit"
                  disabled={savingAiDraftTiming}
                  className="shrink-0 rounded-xl bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
                >
                  {savingAiDraftTiming ? 'Saving...' : 'Save'}
                </button>
              </form>

              <div className="mt-3 border-t border-gray-200 pt-3">
                <label className="flex items-center gap-3 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={autoApplyTemplatesToNewTenants}
                    disabled={savingAutoApplyTemplates}
                    onChange={(event) => saveAutoApplyTemplates(event.target.checked)}
                    className="h-4 w-4 rounded border-gray-300"
                  />
                  Automatically make every shared AI reply template available to newly created tenants
                </label>
                <p className="mt-1 text-xs text-gray-500">
                  When off (default), a new tenant starts with no AI templates available and must be configured manually
                  on the tenant AI settings page.
                </p>
              </div>
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
              <h2 className="text-lg font-semibold text-gray-900">WhatsApp Notification Alerts</h2>
              <p className="mt-1 text-sm text-gray-500">
                When a new notification arrives (inbound WhatsApp or email message from a tenant), users with WhatsApp
                alerts enabled below get a summarized WhatsApp message to their phone. A burst of notifications is batched
                into a single message once things go quiet for this many seconds.
              </p>
              <form onSubmit={saveNotificationWhatsappDebounce} className="mt-3 flex max-w-lg flex-wrap items-end gap-4">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="notification-whatsapp-account">
                    Sending account
                  </label>
                  <select
                    id="notification-whatsapp-account"
                    value={notificationWhatsappExternalAccountId}
                    onChange={(event) => setNotificationWhatsappExternalAccountId(event.target.value)}
                    className="mt-1.5 w-56 rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  >
                    <option value="">Not configured</option>
                    {whatsappAccounts.map((account) => (
                      <option key={account.external_account_id} value={account.external_account_id}>
                        {account.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="notification-whatsapp-debounce-seconds">
                    Alert debounce (seconds)
                  </label>
                  <input
                    id="notification-whatsapp-debounce-seconds"
                    type="number"
                    min={1}
                    value={notificationWhatsappDebounceSeconds}
                    onChange={(event) => setNotificationWhatsappDebounceSeconds(Number(event.target.value))}
                    className="mt-1.5 w-32 rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  />
                </div>
                <button
                  type="submit"
                  disabled={savingNotificationWhatsappDebounce}
                  className="shrink-0 rounded-xl bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
                >
                  {savingNotificationWhatsappDebounce ? 'Saving...' : 'Save'}
                </button>
              </form>
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
              <h2 className="text-lg font-semibold text-gray-900">AI Planner Defaults</h2>
              <p className="mt-1 text-sm text-gray-500">
                The planner reads a conversation, picks a template and drafts a reply, which a checker then proof-reads.
                Configure the agents themselves under Settings &rarr; Planner &amp; Checker, and inspect what they did on the{' '}
                <Link to="/ai-runs" className="text-cyan-700 hover:underline">runs page</Link>.
              </p>
              <form onSubmit={savePlannerDefaults} className="mt-3 flex max-w-2xl flex-wrap items-end gap-4">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-default-mode">
                    Planner mode for new tenants
                  </label>
                  <select
                    id="planner-default-mode"
                    value={plannerDefaultMode}
                    onChange={(event) => setPlannerDefaultMode(event.target.value as 'off' | 'manual' | 'auto-draft' | 'auto-send')}
                    className="mt-1.5 rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  >
                    <option value="off">Off</option>
                    <option value="manual">Manual</option>
                    <option value="auto-draft">Auto-draft</option>
                    <option value="auto-send">Auto-send</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="ai-daily-token-cap">
                    Daily token cap (0 = unlimited)
                  </label>
                  <input
                    id="ai-daily-token-cap"
                    type="number"
                    min={0}
                    value={dailyTokenCap}
                    onChange={(event) => setDailyTokenCap(Number(event.target.value))}
                    className="mt-1.5 w-40 rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  />
                </div>
                <button
                  type="submit"
                  disabled={savingPlannerDefaults}
                  className="shrink-0 rounded-xl bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
                >
                  {savingPlannerDefaults ? 'Saving...' : 'Save'}
                </button>
              </form>
              <p className="mt-2 text-xs text-gray-500">
                Existing tenants are never changed by this setting, so turning it on cannot start drafting for bookings
                already in flight.
              </p>
            </section>
          </>
        ) : null}

        {activeTab === 'logs' ? (
          <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
            <h2 className="text-lg font-semibold text-gray-900">Beds24 Webhook Logs</h2>
            <form className="mt-3 grid gap-3 md:grid-cols-4" onSubmit={applyLogFilters}>
              <select className="rounded-xl border border-gray-300 px-4 py-2.5" value={logStatus} onChange={(e) => setLogStatus(e.target.value)}>
                {logStatuses.map((status) => (
                  <option key={status || 'all'} value={status}>{status || 'All statuses'}</option>
                ))}
              </select>
              <input className="rounded-xl border border-gray-300 px-4 py-2.5" placeholder="Event type" value={logEventType} onChange={(e) => setLogEventType(e.target.value)} />
              <input className="rounded-xl border border-gray-300 px-4 py-2.5" type="datetime-local" value={logStart} onChange={(e) => setLogStart(e.target.value)} />
              <input className="rounded-xl border border-gray-300 px-4 py-2.5" type="datetime-local" value={logEnd} onChange={(e) => setLogEnd(e.target.value)} />
              <button className="rounded-xl bg-gray-900 px-4 py-2.5 font-semibold text-white md:col-span-4">Apply filters</button>
            </form>
            <div className="mt-3 overflow-x-auto">
              {loading ? (
                <p className="py-3 text-sm text-gray-500">Loading webhook logs...</p>
              ) : (
                <table className="min-w-full text-sm">
                  <thead className="text-left text-gray-500">
                    <tr>
                      <th className="py-1.5">Received</th><th>Processed</th><th>Provider</th><th>Event</th><th>Booking</th><th>Tenant</th><th>Status</th><th>HTTP</th><th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {webhookLogs.map((log) => (
                      <tr key={log.id} className="border-t border-gray-100 align-top">
                        <td className="py-2">{new Date(log.received_at).toLocaleString()}</td>
                        <td>{log.processed_at ? new Date(log.processed_at).toLocaleString() : '-'}</td>
                        <td>{log.provider}</td>
                        <td>
                          <div>{log.event_type ?? '-'}</div>
                          {log.external_event_id ? <div className="text-xs text-gray-500">{log.external_event_id}</div> : null}
                        </td>
                        <td>{log.booking_id ?? '-'}</td>
                        <td>{log.tenant_id ?? '-'}</td>
                        <td><span className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${statusClass(log.status)}`}>{log.status}</span></td>
                        <td>{log.http_status ?? '-'}</td>
                        <td className="max-w-xs">
                          <button className="text-left text-cyan-700 underline" type="button" onClick={() => setExpandedLogId((current) => (current === log.id ? null : log.id))}>
                            View details
                          </button>
                          {expandedLogId === log.id ? (
                            <div className="mt-2 space-y-2 rounded-xl border border-gray-200 bg-gray-50 p-2.5 text-xs text-gray-700">
                              <div>
                                <div className="font-semibold text-gray-900">Summary</div>
                                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">{formatJson(log.parsed_fields)}</pre>
                              </div>
                              <div>
                                <div className="font-semibold text-gray-900">Raw payload</div>
                                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">{formatJson(log.raw_payload)}</pre>
                              </div>
                              {log.result_message ? (
                                <div>
                                  <div className="font-semibold text-gray-900">Result</div>
                                  <div className="mt-1">{log.result_message}</div>
                                </div>
                              ) : null}
                              {log.error_summary ? (
                                <div>
                                  <div className="font-semibold text-gray-900">Error summary</div>
                                  <div className="mt-1">{log.error_summary}</div>
                                </div>
                              ) : null}
                              {log.error_traceback ? (
                                <div>
                                  <div className="font-semibold text-gray-900">Error details</div>
                                  <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">{log.error_traceback}</pre>
                                </div>
                              ) : null}
                              <div>
                                <div className="font-semibold text-gray-900">Dedupe key</div>
                                <div className="mt-1 break-all">{log.dedupe_key}</div>
                              </div>
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                    {!webhookLogs.length ? (
                      <tr>
                        <td colSpan={9} className="py-3 text-center text-gray-400">No webhook logs match these filters</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        ) : null}

        {activeTab === 'maintenance' ? (
          <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
            <h2 className="text-lg font-semibold text-gray-900">Email sync maintenance</h2>
            <p className="mt-1 text-sm text-gray-500">
              Re-extract the body and formatted HTML for already-synced Gmail messages from their stored raw payload
              (no Gmail API calls). Use this after a fix to email body extraction to repair messages that were synced
              with a blank or unformatted body.
            </p>
            <button
              type="button"
              disabled={backfillingBodies}
              onClick={backfillEmailBodies}
              className="mt-3 rounded-xl bg-cyan-600 px-4 py-2.5 font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
            >
              {backfillingBodies ? 'Backfilling...' : 'Backfill email bodies'}
            </button>
          </section>
        ) : null}
      </SettingsSidebarLayout>

      {showCreateUserModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 px-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <h2 className="text-xl font-semibold text-gray-900">Create user</h2>
              <button type="button" onClick={() => setShowCreateUserModal(false)} className="text-sm text-gray-500 hover:text-gray-900">Close</button>
            </div>
            <form className="mt-3 space-y-2" onSubmit={createUser}>
              <div>
                <label className="mb-1 block text-xs text-gray-500">Full name</label>
                <input
                  className="w-full rounded-xl border border-gray-300 px-4 py-2"
                  value={newUser.full_name}
                  onChange={(e) => setNewUser((current) => ({ ...current, full_name: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">Email address</label>
                <input
                  type="email"
                  required
                  className="w-full rounded-xl border border-gray-300 px-4 py-2"
                  value={newUser.email}
                  onChange={(e) => setNewUser((current) => ({ ...current, email: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">Phone</label>
                <input
                  className="w-full rounded-xl border border-gray-300 px-4 py-2"
                  value={newUser.phone}
                  onChange={(e) => setNewUser((current) => ({ ...current, phone: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">Role</label>
                <select
                  className="w-full rounded-xl border border-gray-300 px-4 py-2"
                  value={newUser.is_admin ? 'admin' : 'non-admin'}
                  onChange={(e) => setNewUser((current) => ({ ...current, is_admin: e.target.value === 'admin' }))}
                >
                  <option value="non-admin">Non-admin</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">Password</label>
                <input
                  type="password"
                  required
                  minLength={8}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2"
                  value={newUser.password}
                  onChange={(e) => setNewUser((current) => ({ ...current, password: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-500">Confirm password</label>
                <input
                  type="password"
                  required
                  minLength={8}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2"
                  value={newUser.password_confirmation}
                  onChange={(e) => setNewUser((current) => ({ ...current, password_confirmation: e.target.value }))}
                />
              </div>
              {createUserError ? <p className="text-sm text-rose-600">{createUserError}</p> : null}
              <div className="mt-3 flex justify-end gap-3">
                <button type="button" onClick={() => setShowCreateUserModal(false)} className="rounded-xl px-4 py-2 text-sm text-gray-500 hover:text-gray-900">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingUser}
                  className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
                >
                  {creatingUser ? 'Creating...' : 'Create user'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {deleteTarget ? (
        <ConfirmDialog
          title={`Delete ${deleteTarget.full_name || deleteTarget.email}?`}
          description="This permanently removes this user's ability to sign in. This action cannot be undone."
          confirmLabel="Delete user"
          confirmingLabel="Deleting..."
          loading={deletingUser}
          error={deleteUserError}
          onConfirm={confirmDeleteUser}
          onCancel={() => setDeleteTarget(null)}
        />
      ) : null}

      {showClearInvitesModal ? (
        <ConfirmDialog
          title="Clear all pending invite links?"
          description="This will invalidate all pending invite links. People who already received an invite link will no longer be able to use it. Existing users are not affected."
          confirmLabel="Clear pending invite links"
          confirmingLabel="Clearing..."
          loading={clearingInvites}
          error={clearInvitesError}
          onConfirm={confirmClearInvites}
          onCancel={() => setShowClearInvitesModal(false)}
        />
      ) : null}

      <ToastHost toast={toast} onDismiss={dismiss} />
    </>
  )
}
