import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { clearDirectoryHandleForUser, getDirectoryHandleForUser, setDirectoryHandleForUser } from '../lib/fileHandleStore'
import { useRelativeTimestampsPreference } from '../lib/displayPreferences'

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

export default function Settings() {
  const token = useAuthStore((state) => state.token)
  const userEmail = useAuthStore((state) => state.user?.email)
  const userKey = userEmail ?? 'anonymous'
  const [relativeTimestamps, setRelativeTimestamps] = useRelativeTimestampsPreference()
  const [savedHandle, setSavedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [stagedHandle, setStagedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [permissionState, setPermissionState] = useState<'granted' | 'prompt' | 'denied' | null>(null)
  const [unsupported, setUnsupported] = useState(false)
  const [saving, setSaving] = useState(false)
  const [gmailAccounts, setGmailAccounts] = useState<GmailAccount[]>([])
  const [gmailMessage, setGmailMessage] = useState('')

  const loadGmailAccounts = async () => {
    const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) setGmailAccounts(await response.json())
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
    <main className="mx-auto max-w-4xl px-6 py-6">
      <h1 className="text-2xl font-semibold text-gray-900">Settings</h1>
      <p className="text-sm text-gray-500">{userEmail ?? 'Signed in'}</p>

      <section className="mt-8 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Display</h2>
        <p className="mt-2 text-sm text-gray-500">Choose how timestamps are shown in the thread view.</p>

        <label className="mt-4 flex items-center gap-3 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={relativeTimestamps}
            onChange={(event) => setRelativeTimestamps(event.target.checked)}
            className="h-4 w-4 rounded border-gray-300"
          />
          Use relative timestamps (e.g. "30min ago", "4h ago", "2 days ago") instead of exact date and time
        </label>
      </section>

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Shared Gmail setup</h2>
        <p className="mt-2 text-sm text-gray-500">
          Connect Gmail accounts once for the organization. All users use the same synced mailbox list.
        </p>

        <div className="mt-4 flex flex-wrap gap-3">
          <button type="button" className="rounded-xl bg-cyan-600 px-4 py-3 font-semibold text-white" onClick={() => startGmailOAuth()}>
            Connect Gmail account
          </button>
          <button type="button" className="rounded-xl border border-gray-300 px-4 py-3 font-semibold text-gray-900" onClick={loadGmailAccounts}>
            Refresh list
          </button>
          <button type="button" className="rounded-xl border border-gray-300 px-4 py-3 font-semibold text-gray-900" onClick={syncAllGmailAccounts}>
            Sync all active
          </button>
        </div>

        {gmailMessage ? <p className="mt-3 text-sm text-gray-600">{gmailMessage}</p> : null}

        <div className="mt-5 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="py-2">Email</th><th>Display</th><th>Status</th><th>Last sync</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {gmailAccounts.map((account) => (
                <tr key={account.id} className="border-t border-gray-100">
                  <td className="py-3">{account.email_address}</td>
                  <td>{account.display_name ?? '-'}</td>
                  <td>
                    <div className="flex items-center gap-2">{account.is_active ? statusDot('green') : statusDot('gray')}<span>{account.is_active ? 'Active' : 'Disconnected'}</span></div>
                  </td>
                  <td>{account.last_synced_at ? new Date(account.last_synced_at).toLocaleString() : '-'}</td>
                  <td className="space-x-2 py-3">
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

      <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Local Folder</h2>
        <p className="mt-2 text-sm text-gray-500">
          Select the root folder on your computer where tenant files are stored. This setting is saved per user and restored on each visit.
        </p>

        {unsupported ? (
          <p className="mt-4 text-sm text-gray-600">Local folder access is not supported in this browser.</p>
        ) : (
          <div className="mt-4 space-y-4">
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
          </div>
        )}
      </section>
    </main>
  )
}
