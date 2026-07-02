import { FormEvent, useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type UserRow = {
  id: number
  email: string
  full_name: string | null
  phone: string | null
  is_active: boolean
  is_admin: boolean
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
  received_at: string
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

function formatJson(value: unknown) {
  return JSON.stringify(value ?? null, null, 2)
}

export default function AdminSettings() {
  const token = useAuthStore((state) => state.token)
  const [users, setUsers] = useState<UserRow[]>([])
  const [invites, setInvites] = useState<InviteRow[]>([])
  const [webhookLogs, setWebhookLogs] = useState<Beds24WebhookLogRow[]>([])
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteName, setInviteName] = useState('')
  const [invitePhone, setInvitePhone] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'non-admin'>('non-admin')
  const [message, setMessage] = useState('')
  const [logStatus, setLogStatus] = useState('')
  const [logEventType, setLogEventType] = useState('')
  const [logStart, setLogStart] = useState('')
  const [logEnd, setLogEnd] = useState('')
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null)

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
    if (response.ok) setWebhookLogs(await response.json())
  }

  useEffect(() => {
    const load = async () => {
      const [usersResponse, invitesResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/users`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined }),
        fetch(`${API_BASE_URL}/api/admin/invites`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined }),
      ])
      if (usersResponse.ok) setUsers(await usersResponse.json())
      if (invitesResponse.ok) setInvites(await invitesResponse.json())
      await loadLogs()
    }
    load()
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
    setMessage('')
    const response = await fetch(`${API_BASE_URL}/api/admin/invites`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ email: inviteEmail || null, full_name: inviteName || null, phone: invitePhone || null, role: inviteRole }),
    })
    const data = await response.json()
    if (!response.ok) {
      setMessage(data.detail ?? 'Failed to create invite')
      return
    }
    if (data.invite_url) {
      await navigator.clipboard.writeText(data.invite_url).catch(() => undefined)
      setInvites((current) => [{ ...data }, ...current.filter((invite) => invite.id !== data.id)])
      setMessage(`Invitation created and copied: ${data.invite_url}`)
    } else {
      setMessage('Invitation created')
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
    setMessage('Invite link copied')
  }

  const revokeInvite = async (inviteId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/admin/invites/${inviteId}/revoke`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) await refresh()
  }

  const regenerateInvite = async (inviteId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/admin/invites/${inviteId}/regenerate`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) await refresh()
  }

  const toggleActive = async (userId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/users/${userId}/toggle-active`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) await refresh()
  }

  const sendReset = async (userId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/users/${userId}/password-reset`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    const data = await response.json()
    setMessage(response.ok ? `Password reset link created: ${data.reset_url}` : data.detail ?? 'Failed to create reset link')
  }

  const applyLogFilters = async (event: FormEvent) => {
    event.preventDefault()
    await loadLogs()
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="text-2xl font-semibold text-gray-900">Admin Settings</h1>
      <p className="mt-1 text-sm text-gray-500">User management, invite onboarding, password resets, and Beds24 webhook logs.</p>

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Generate invite link</h2>
        <form className="mt-4 grid gap-3 md:grid-cols-5" onSubmit={createInvite}>
          <input className="rounded-xl border border-gray-300 px-4 py-3" placeholder="Email (optional)" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} />
          <input className="rounded-xl border border-gray-300 px-4 py-3" placeholder="Full name" value={inviteName} onChange={(e) => setInviteName(e.target.value)} />
          <input className="rounded-xl border border-gray-300 px-4 py-3" placeholder="Phone" value={invitePhone} onChange={(e) => setInvitePhone(e.target.value)} />
          <select className="rounded-xl border border-gray-300 px-4 py-3" value={inviteRole} onChange={(e) => setInviteRole(e.target.value as 'admin' | 'non-admin')}>
            <option value="non-admin">Non-admin</option>
            <option value="admin">Admin</option>
          </select>
          <button className="rounded-xl bg-cyan-600 px-4 py-3 font-semibold text-white">Generate invite link</button>
        </form>
        {message ? <p className="mt-3 text-sm text-gray-600">{message}</p> : null}
      </section>

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Invite management</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="py-2">Email</th><th>Name</th><th>Phone</th><th>Role</th><th>Status</th><th>Expires</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {invites.map((invite) => (
                <tr key={invite.id} className="border-t border-gray-100">
                  <td className="py-3">{invite.email ?? '-'}</td>
                  <td>{invite.full_name ?? '-'}</td>
                  <td>{invite.phone ?? '-'}</td>
                  <td>{invite.role}</td>
                  <td>{invite.status}</td>
                  <td>{new Date(invite.expires_at).toLocaleString()}</td>
                  <td className="space-x-2 py-3">
                    <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => copyInvite(invite)} type="button" disabled={!invite.invite_url}>Copy link</button>
                    <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => revokeInvite(invite.id)} type="button" disabled={invite.status === 'revoked' || invite.status === 'completed'}>Revoke</button>
                    <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => regenerateInvite(invite.id)} type="button" disabled={invite.status === 'completed'}>Regenerate</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Beds24 Webhook Logs</h2>
        <form className="mt-4 grid gap-3 md:grid-cols-4" onSubmit={applyLogFilters}>
          <select className="rounded-xl border border-gray-300 px-4 py-3" value={logStatus} onChange={(e) => setLogStatus(e.target.value)}>
            {logStatuses.map((status) => (
              <option key={status || 'all'} value={status}>{status || 'All statuses'}</option>
            ))}
          </select>
          <input className="rounded-xl border border-gray-300 px-4 py-3" placeholder="Event type" value={logEventType} onChange={(e) => setLogEventType(e.target.value)} />
          <input className="rounded-xl border border-gray-300 px-4 py-3" type="datetime-local" value={logStart} onChange={(e) => setLogStart(e.target.value)} />
          <input className="rounded-xl border border-gray-300 px-4 py-3" type="datetime-local" value={logEnd} onChange={(e) => setLogEnd(e.target.value)} />
          <button className="rounded-xl bg-gray-900 px-4 py-3 font-semibold text-white md:col-span-4">Apply filters</button>
        </form>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="py-2">Received</th><th>Event</th><th>Booking</th><th>Room</th><th>Tenant</th><th>Status</th><th>HTTP</th><th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {webhookLogs.map((log) => (
                <tr key={log.id} className="border-t border-gray-100 align-top">
                  <td className="py-3">{new Date(log.received_at).toLocaleString()}</td>
                  <td>{log.event_type ?? '-'}</td>
                  <td>{log.booking_id ?? '-'}</td>
                  <td>{log.room_id ?? '-'}</td>
                  <td>{log.tenant_id ?? '-'}</td>
                  <td>{log.status}</td>
                  <td>{log.http_status ?? '-'}</td>
                  <td className="max-w-xs">
                    <button className="text-left text-cyan-700 underline" type="button" onClick={() => setExpandedLogId((current) => (current === log.id ? null : log.id))}>
                      {log.result_message ?? log.error_summary ?? 'View details'}
                    </button>
                    {expandedLogId === log.id ? (
                      <div className="mt-3 space-y-3 rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
                        <div>
                          <div className="font-semibold text-gray-900">Raw payload</div>
                          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">{formatJson(log.raw_payload)}</pre>
                        </div>
                        <div>
                          <div className="font-semibold text-gray-900">Parsed fields</div>
                          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">{formatJson(log.parsed_fields)}</pre>
                        </div>
                        {log.error_traceback ? (
                          <div>
                            <div className="font-semibold text-gray-900">Error details</div>
                            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">{log.error_traceback}</pre>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Users</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="py-2">Name</th><th>Email</th><th>Phone</th><th>Status</th><th>Role</th><th>Created</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-t border-gray-100">
                  <td className="py-3">{user.full_name ?? '-'}</td>
                  <td>{user.email}</td>
                  <td>{user.phone ?? '-'}</td>
                  <td>{user.is_active ? 'Active' : 'Inactive'}</td>
                  <td>{user.is_admin ? 'Admin' : 'User'}</td>
                  <td>{new Date(user.created_at).toLocaleString()}</td>
                  <td className="space-x-2 py-3">
                    <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => toggleActive(user.id)} type="button">Toggle active</button>
                    <button className="rounded-lg border border-gray-300 px-3 py-1" onClick={() => sendReset(user.id)} type="button">Send password reset</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  )
}
