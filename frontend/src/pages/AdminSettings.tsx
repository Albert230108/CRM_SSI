import { FormEvent, useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type UserRow = {
  id: number
  email: string
  full_name: string | null
  is_active: boolean
  is_admin: boolean
  created_at: string
}

export default function AdminSettings() {
  const token = useAuthStore((state) => state.token)
  const [users, setUsers] = useState<UserRow[]>([])
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteName, setInviteName] = useState('')
  const [inviteAdmin, setInviteAdmin] = useState(false)
  const [inviteUrl, setInviteUrl] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    const load = async () => {
      const response = await fetch(`${API_BASE_URL}/api/users`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined })
      if (response.ok) setUsers(await response.json())
    }
    load()
  }, [token])

  const refresh = async () => {
    const response = await fetch(`${API_BASE_URL}/api/users`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined })
    if (response.ok) setUsers(await response.json())
  }

  const createInvite = async (event: FormEvent) => {
    event.preventDefault()
    setMessage('')
    setInviteUrl('')
    const response = await fetch(`${API_BASE_URL}/api/users/invite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ email: inviteEmail, full_name: inviteName || null, is_admin: inviteAdmin }),
    })
    const data = await response.json()
    if (!response.ok) {
      setMessage(data.detail ?? 'Failed to create invite')
      return
    }
    setInviteUrl(data.invite_url)
    setMessage('Invitation created')
    await refresh()
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

  return (
    <main className="mx-auto max-w-6xl px-6 py-6">
      <h1 className="text-2xl font-semibold text-gray-900">Admin Settings</h1>
      <p className="mt-1 text-sm text-gray-500">User management, invitations, and password resets.</p>

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Invite user</h2>
        <form className="mt-4 grid gap-3 md:grid-cols-4" onSubmit={createInvite}>
          <input className="rounded-xl border border-gray-300 px-4 py-3" placeholder="Email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} required />
          <input className="rounded-xl border border-gray-300 px-4 py-3" placeholder="Full name" value={inviteName} onChange={(e) => setInviteName(e.target.value)} />
          <label className="flex items-center gap-2 rounded-xl border border-gray-300 px-4 py-3 text-sm text-gray-700"><input type="checkbox" checked={inviteAdmin} onChange={(e) => setInviteAdmin(e.target.checked)} /> Admin</label>
          <button className="rounded-xl bg-cyan-600 px-4 py-3 font-semibold text-white">Create invite</button>
        </form>
        {inviteUrl ? <p className="mt-3 break-all text-sm text-cyan-700">{inviteUrl}</p> : null}
        {message ? <p className="mt-2 text-sm text-gray-600">{message}</p> : null}
      </section>

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Users</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="py-2">Name</th><th>Email</th><th>Status</th><th>Role</th><th>Created</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-t border-gray-100">
                  <td className="py-3">{user.full_name ?? '-'}</td>
                  <td>{user.email}</td>
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
