import { useEffect, useState, type MouseEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import ImportModal from './ImportModal'
import NotificationBell from './NotificationBell'
import SyncProgressOverlay from './SyncProgressOverlay'
import ToastCard from './ToastCard'
import { useAuthStore } from '../store/authStore'
import { useNotesDraftStore } from '../store/notesDraftStore'
import { useSyncStore } from '../store/syncStore'
import crmLogo from '../assets/logo.jpg'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type SyncSummary = {
  started_at: string
  completed_at: string | null
  bookings_updated: number
  emails_imported: number
  whatsapp_messages_imported: number
  whatsapp_sync_queued?: boolean
  tenant_threads_updated: number
  partial_failures: { step: string; error: string }[]
}

function formatSyncSummary(summary: SyncSummary | null) {
  if (!summary) return ''
  return [
    `Bookings updated: ${summary.bookings_updated}`,
    `Emails imported: ${summary.emails_imported}`,
    summary.whatsapp_sync_queued ? 'WhatsApp sync queued in background' : `WhatsApp messages imported: ${summary.whatsapp_messages_imported}`,
    `Tenant threads updated: ${summary.tenant_threads_updated}`,
  ].join(' � ')
}

export default function Navbar() {
  const location = useLocation()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const token = useAuthStore((state) => state.token)
  const logout = useAuthStore((state) => state.logout)
  const settingsActive = location.pathname.startsWith('/settings')
  const adminActive = location.pathname.startsWith('/admin')
  const aiDraftsActive = location.pathname.startsWith('/ai-drafts')
  const [pendingAiDraftsCount, setPendingAiDraftsCount] = useState(0)
  const notifySyncCompleted = useSyncStore((state) => state.notifySyncCompleted)
  const notifyImportCompleted = useSyncStore((state) => state.notifyImportCompleted)

  const [importModalOpen, setImportModalOpen] = useState(false)
  const [syncRunning, setSyncRunning] = useState(false)
  const [syncSummary, setSyncSummary] = useState<SyncSummary | null>(null)
  const [syncError, setSyncError] = useState('')
  const [syncToken, setSyncToken] = useState(0)
  const [toastVisible, setToastVisible] = useState(false)

  useEffect(() => {
    if (!token) return
    let cancelled = false

    const pollPendingAiDrafts = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!response.ok || cancelled) return
        const data: unknown[] = await response.json()
        setPendingAiDraftsCount(data.length)
      } catch {
        // Ignore transient poll failures; next interval tick will retry.
      }
    }

    pollPendingAiDrafts()
    const intervalId = window.setInterval(pollPendingAiDrafts, 15000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [token])

  const aiDraftsBadgeLabel = pendingAiDraftsCount > 9 ? '9+' : String(pendingAiDraftsCount)

  // Intercepts in-app link clicks so leaving with unsaved notes prompts the
  // unsaved-notes modal instead of silently discarding the edit.
  const guardedNavigate = (event: MouseEvent<HTMLAnchorElement>, to: string) => {
    event.preventDefault()
    useNotesDraftStore.getState().guardNavigation(() => navigate(to))
  }

  const guardedLogout = () => {
    useNotesDraftStore.getState().guardNavigation(logout)
  }

  useEffect(() => {
    if (!syncSummary?.whatsapp_sync_queued) {
      return
    }

    let cancelled = false

    const refreshSyncStatus = async () => {
      try {
        const statusResponse = await fetch(`${API_BASE_URL}/api/admin/sync-status`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        const statusPayload = await statusResponse.json().catch(() => null)
        if (!statusResponse.ok || cancelled) {
          return
        }
        if (!statusPayload?.whatsapp_sync_running) {
          setSyncSummary((current) => (current ? { ...current, whatsapp_sync_queued: false } : current))
          notifySyncCompleted()
        }
      } catch {
        // Keep the banner in queued state until the next poll succeeds.
      }
    }

    void refreshSyncStatus()
    const intervalId = window.setInterval(refreshSyncStatus, 5000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [syncSummary?.whatsapp_sync_queued, token, notifySyncCompleted])

  // Show the sync toast for exactly 8s per completed attempt. Keyed on syncToken
  // (not syncSummary) so the later background queued-status poll, which quietly
  // mutates syncSummary, doesn't re-trigger or extend the toast.
  useEffect(() => {
    if (syncToken === 0) return
    setToastVisible(true)
    const timeoutId = window.setTimeout(() => setToastVisible(false), 8000)
    return () => window.clearTimeout(timeoutId)
  }, [syncToken])

  const handleSyncAll = async () => {
    if (syncRunning) return
    try {
      setSyncRunning(true)
      setSyncError('')
      setSyncSummary(null)
      const syncUrl = `${API_BASE_URL}/api/admin/sync-all`
      console.info('[frontend] Sync button clicked', { syncUrl })
      const response = await fetch(syncUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ tenant_ids: null }),
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(payload?.detail || 'Sync failed')
      }
      setSyncSummary(payload as SyncSummary)
      notifySyncCompleted()
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : 'Sync failed')
    } finally {
      setSyncRunning(false)
      setSyncToken((current) => current + 1)
    }
  }

  return (
    <>
      <header className="relative z-50 w-full border-b border-gray-200 bg-white backdrop-blur">
        <div className="flex w-full items-center justify-between px-6 py-4">
          <Link to="/" onClick={(event) => guardedNavigate(event, '/')} className="flex items-center gap-3">
            <img src={crmLogo} alt="CRM logo" className="h-8 w-auto" />
            <h1 className="text-base font-semibold text-gray-900 transition hover:text-gray-700">CRM SSI</h1>
          </Link>
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-500">{user?.full_name || user?.email || 'Signed in'}</span>
            <NotificationBell />
            {user?.is_admin ? (
              <Link
                to="/admin/settings"
                onClick={(event) => guardedNavigate(event, '/admin/settings')}
                className={`inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${adminActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
              >
                <span>Admin Settings</span>
              </Link>
            ) : null}
            <Link
              to="/ai-drafts"
              onClick={(event) => guardedNavigate(event, '/ai-drafts')}
              className={`relative inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${aiDraftsActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
            >
              <span>AI Drafts</span>
              {pendingAiDraftsCount > 0 ? (
                <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold leading-none text-white">
                  {aiDraftsBadgeLabel}
                </span>
              ) : null}
            </Link>
            <Link
              to="/settings"
              onClick={(event) => guardedNavigate(event, '/settings')}
              className={`inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${settingsActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
            >
              <span>Settings</span>
            </Link>
            <button
              type="button"
              onClick={handleSyncAll}
              disabled={syncRunning}
              className="rounded-lg border border-cyan-500/40 bg-white px-3 py-1.5 text-sm font-semibold text-cyan-700 transition hover:bg-cyan-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {syncRunning ? 'Syncing...' : 'Sync'}
            </button>
            <button
              type="button"
              onClick={() => setImportModalOpen(true)}
              className="rounded-lg border border-cyan-500/40 bg-cyan-600 px-3 py-1.5 text-sm font-semibold text-white transition hover:bg-cyan-700"
            >
              Import Beds24 bookings
            </button>
            <button
              onClick={guardedLogout}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      <SyncProgressOverlay active={syncRunning} />

      <ImportModal
        open={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        onImported={notifyImportCompleted}
      />

      {toastVisible && (syncSummary || syncError) ? (
        <div className="fixed right-4 top-20 z-50 flex flex-col gap-2">
          <ToastCard toastKey={syncToken} tone={syncError ? 'error' : 'success'} durationMs={8000}>
            {syncError ? (
              <p className="font-semibold">{syncError}</p>
            ) : syncSummary ? (
              <>
                <p className="font-semibold">{syncSummary.whatsapp_sync_queued ? 'Sync started' : 'Sync complete'}</p>
                <p className="mt-1">{formatSyncSummary(syncSummary)}</p>
                {syncSummary.whatsapp_sync_queued ? (
                  <p className="mt-2 text-xs text-emerald-800/80">WhatsApp history sync continues in the background.</p>
                ) : null}
                {syncSummary.partial_failures.length ? (
                  <p className="mt-2 text-xs text-emerald-800/80">
                    Partial failures: {syncSummary.partial_failures.map((item) => `${item.step}: ${item.error}`).join(' | ')}
                  </p>
                ) : null}
              </>
            ) : null}
          </ToastCard>
        </div>
      ) : null}
    </>
  )
}
