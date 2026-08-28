import { useEffect, useState, type MouseEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import AiSettingsDropdown from './AiSettingsDropdown'
import ImportModal from './ImportModal'
import NotificationBell from './NotificationBell'
import SyncProgressOverlay from './SyncProgressOverlay'
import ToastCard from './ToastCard'
import { withAiSettingsReturn } from '../lib/aiSettingsNavigation'
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
  tenant_threads_updated: number
  partial_failures: { step: string; error: string }[]
}

function formatSyncSummary(summary: SyncSummary | null) {
  if (!summary) return ''
  return [
    `Bookings updated: ${summary.bookings_updated}`,
    `Emails imported: ${summary.emails_imported}`,
    `WhatsApp messages imported: ${summary.whatsapp_messages_imported}`,
    `Tenant threads updated: ${summary.tenant_threads_updated}`,
  ].join(' Â· ')
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
  const plannerSchedulesActive = location.pathname.startsWith('/settings/planner-schedules')
  const actionsActive = location.pathname.startsWith('/actions')
  const workingMemoryActive = location.pathname.startsWith('/working-memory')
  const [pendingAiDraftsCount, setPendingAiDraftsCount] = useState(0)
  const [pendingActionsCount, setPendingActionsCount] = useState(0)
  const notifySyncCompleted = useSyncStore((state) => state.notifySyncCompleted)
  const notifyImportCompleted = useSyncStore((state) => state.notifyImportCompleted)
  const syncJobId = useSyncStore((state) => state.syncJobId)
  const syncProgress = useSyncStore((state) => state.syncProgress)
  const setSyncJob = useSyncStore((state) => state.setSyncJob)
  const setSyncProgress = useSyncStore((state) => state.setSyncProgress)

  const [importModalOpen, setImportModalOpen] = useState(false)
  // Seeded from the store so a remount during an in-flight job (e.g. after navigating) shows
  // the button as busy instead of inviting a second run.
  const [syncRunning, setSyncRunning] = useState(Boolean(syncJobId))
  const [syncSummary, setSyncSummary] = useState<SyncSummary | null>(null)
  const [syncError, setSyncError] = useState('')
  const [syncToken, setSyncToken] = useState(0)
  const [toastVisible, setToastVisible] = useState(false)

  useEffect(() => {
    if (!token) return
    let cancelled = false

    const pollCounts = async () => {
      try {
        const [draftsResponse, openActionsResponse, pendingSuggestionsResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/ai-auto-drafts`, { headers: { Authorization: `Bearer ${token}` } }),
          fetch(`${API_BASE_URL}/api/action-items?status=open`, { headers: { Authorization: `Bearer ${token}` } }),
          fetch(`${API_BASE_URL}/api/action-items/pending-suggestions`, { headers: { Authorization: `Bearer ${token}` } }),
        ])
        if (cancelled) return
        if (draftsResponse.ok) {
          const data: unknown[] = await draftsResponse.json()
          setPendingAiDraftsCount(data.length)
        }
        if (openActionsResponse.ok && pendingSuggestionsResponse.ok) {
          const [openActions, pendingSuggestions]: [unknown[], unknown[]] = await Promise.all([
            openActionsResponse.json(),
            pendingSuggestionsResponse.json(),
          ])
          setPendingActionsCount(openActions.length + pendingSuggestions.length)
        }
      } catch {
        // Ignore transient poll failures; next interval tick will retry.
      }
    }

    pollCounts()
    const intervalId = window.setInterval(pollCounts, 15000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [token])

  const formatBadgeCount = (count: number) => (count > 9 ? '9+' : String(count))

  // Intercepts in-app link clicks so leaving with unsaved notes prompts the
  // unsaved-notes modal instead of silently discarding the edit.
  const guardedNavigate = (event: MouseEvent<HTMLAnchorElement>, to: string) => {
    event.preventDefault()
    useNotesDraftStore.getState().guardNavigation(() => navigate(to))
  }

  const guardedLogout = () => {
    useNotesDraftStore.getState().guardNavigation(logout)
  }

  // Escape hatch for a wedged run. Cancelling server-side matters as much as clearing the
  // overlay: while the job is still reported as running, the single-flight guard refuses to
  // start a new sync. A failed cancel (e.g. non-admin) must still free the UI.
  const handleAbandonSync = async () => {
    const jobId = syncJobId
    setSyncJob(null)
    setSyncRunning(false)
    if (!jobId) return
    try {
      await fetch(`${API_BASE_URL}/api/admin/sync-all/${jobId}/cancel`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
    } catch {
      // Best effort: the UI is already unblocked.
    }
  }

  // sync-all is a backend job: the POST only hands back a job id, so completion is observed
  // by polling. Keyed on syncJobId (which lives in syncStore) so a run started before a route
  // change is picked back up when Navbar remounts, rather than being abandoned mid-flight.
  useEffect(() => {
    if (!syncJobId) return

    let cancelled = false

    const finish = (summary: SyncSummary | null, error: string) => {
      if (cancelled) return
      if (summary) setSyncSummary(summary)
      if (error) setSyncError(error)
      setSyncJob(null)
      setSyncRunning(false)
      setSyncToken((current) => current + 1)
      if (!error) notifySyncCompleted()
    }

    const pollJob = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/admin/sync-all/${syncJobId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (cancelled) return
        if (response.status === 404) {
          // The job registry is process-memory, so a backend restart drops in-flight jobs.
          // Treat that as "over" and refresh, rather than polling a job that can never return.
          finish(null, 'Sync status was lost (the server restarted). Data may still have been updated.')
          return
        }
        const job = await response.json().catch(() => null)
        if (!response.ok || !job || cancelled) return
        setSyncProgress(job.progress ?? {})
        if (job.status === 'done') {
          finish(job.result as SyncSummary, '')
        } else if (job.status === 'error') {
          finish(null, job.error || 'Sync failed')
        }
      } catch {
        // Transient network failure: keep polling, the next tick will retry.
      }
    }

    void pollJob()
    const intervalId = window.setInterval(pollJob, 2000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [syncJobId, token, notifySyncCompleted, setSyncJob, setSyncProgress])

  // Show the sync toast for exactly 8s per completed attempt. Keyed on syncToken (not
  // syncSummary) so it fires once per finished run, and a re-render carrying the same
  // summary doesn't re-trigger or extend the toast.
  useEffect(() => {
    if (syncToken === 0) return
    setToastVisible(true)
    const timeoutId = window.setTimeout(() => setToastVisible(false), 8000)
    return () => window.clearTimeout(timeoutId)
  }, [syncToken])

  // Only starts the job; the polling effect above owns completion, so syncRunning is cleared
  // there rather than in a finally here.
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
      if (!payload?.job_id) {
        throw new Error('Sync did not return a job id')
      }
      setSyncJob(payload.job_id as string)
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : 'Sync failed')
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
                  {formatBadgeCount(pendingAiDraftsCount)}
                </span>
              ) : null}
            </Link>
            <Link
              to="/settings/planner-schedules"
              onClick={(event) => guardedNavigate(event, '/settings/planner-schedules')}
              className={`inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${plannerSchedulesActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
            >
              <span>Planner Schedules</span>
            </Link>
            <Link
              to="/actions"
              onClick={(event) => guardedNavigate(event, '/actions')}
              className={`relative inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${actionsActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
            >
              <span>Actions</span>
              {pendingActionsCount > 0 ? (
                <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold leading-none text-white">
                  {formatBadgeCount(pendingActionsCount)}
                </span>
              ) : null}
            </Link>
            <Link
              to="/working-memory"
              onClick={(event) => guardedNavigate(event, '/working-memory')}
              className={`inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${workingMemoryActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
            >
              <span>Working Memory</span>
            </Link>
            <AiSettingsDropdown onNavigate={guardedNavigate}>
              <Link
                to={withAiSettingsReturn('/settings/ai-templates')}
                onClick={(event) => guardedNavigate(event, withAiSettingsReturn('/settings/ai-templates'))}
                className={`inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${location.pathname.startsWith('/settings/ai-templates') ? 'font-medium text-gray-900' : 'text-gray-500'}`}
              >
                <span>AI Settings</span>
              </Link>
            </AiSettingsDropdown>
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

      <SyncProgressOverlay active={syncRunning} progress={syncProgress} onDismiss={handleAbandonSync} />

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
                <p className="font-semibold">Sync complete</p>
                <p className="mt-1">{formatSyncSummary(syncSummary)}</p>
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
