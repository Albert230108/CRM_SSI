import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import FinanceBox from '../components/FinanceBox'
import ImportModal from '../components/ImportModal'
import OneDriveBox from '../components/OneDriveBox'
import TenantList from '../components/TenantList'
import ThreadView from '../components/ThreadView'
import { useAuthStore } from '../store/authStore'

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

export default function Dashboard() {
  const token = useAuthStore((state) => state.token)
  const { tenantId } = useParams()
  const selectedTenantId = useMemo(() => {
    const parsed = Number(tenantId)
    return Number.isFinite(parsed) ? parsed : undefined
  }, [tenantId])
  
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [tenantsCollapsed, setTenantsCollapsed] = useState(false)
  const [tenantReloadSignal, setTenantReloadSignal] = useState(0)
  const [syncRunning, setSyncRunning] = useState(false)
  const [syncSummary, setSyncSummary] = useState<SyncSummary | null>(null)
  const [syncError, setSyncError] = useState('')

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 767px)')
    const updateCollapsedState = () => setTenantsCollapsed(mediaQuery.matches)

    updateCollapsedState()
    mediaQuery.addEventListener('change', updateCollapsedState)
    return () => mediaQuery.removeEventListener('change', updateCollapsedState)
  }, [])

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
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(payload?.detail || 'Sync failed')
      }
      setSyncSummary(payload as SyncSummary)
      setTenantReloadSignal((current) => current + 1)
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : 'Sync failed')
    } finally {
      setSyncRunning(false)
    }
  }

  return (
    <main className="flex h-screen w-full flex-col overflow-hidden px-6 py-6">
      <div className="mb-5 flex w-full items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold text-gray-900">Dashboard</h1>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleSyncAll}
            disabled={syncRunning}
            className="rounded-xl border border-cyan-500/40 bg-white px-4 py-2 text-sm font-semibold text-cyan-700 transition hover:bg-cyan-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {syncRunning ? 'Syncing...' : 'Sync'}
          </button>
          <button
            type="button"
            onClick={() => setImportModalOpen(true)}
            className="rounded-xl border border-cyan-500/40 bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-700"
          >
            Import Beds24 bookings
          </button>
        </div>
      </div>

      {syncRunning ? <p className="mb-3 text-sm text-cyan-700">Running unified sync job...</p> : null}
      {syncError ? <p className="mb-3 text-sm text-rose-500">{syncError}</p> : null}
      {syncSummary ? (
        <div className="mb-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          <p className="font-semibold">{syncSummary.whatsapp_sync_queued ? "Sync started" : "Sync complete"}</p>
          <p className="mt-1">{formatSyncSummary(syncSummary)}</p>
          {syncSummary.whatsapp_sync_queued ? (
            <p className="mt-2 text-xs text-emerald-800/80">WhatsApp history sync continues in the background.</p>
          ) : null}
          {syncSummary.partial_failures.length ? (
            <p className="mt-2 text-xs text-emerald-800/80">
              Partial failures: {syncSummary.partial_failures.map((item) => `${item.step}: ${item.error}`).join(' | ')}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-row gap-4 flex-1 min-h-0 overflow-hidden">
        <section
          className={[
            'relative flex h-full shrink-0 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm transition-all duration-300',
            tenantsCollapsed ? 'w-10' : 'w-[260px]',
          ].join(' ')}
        >
          <button
            type="button"
            onClick={() => setTenantsCollapsed((current) => !current)}
            aria-label={tenantsCollapsed ? 'Expand tenants panel' : 'Collapse tenants panel'}
            className="absolute right-0 top-4 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-l-xl border border-gray-200 border-r-0 bg-white text-sm font-semibold text-gray-600 shadow-sm transition hover:bg-gray-50"
          >
            {tenantsCollapsed ? '▶' : '◀'}
          </button>
          <div
            className={[
              'h-full min-w-[260px] overflow-hidden p-5 transition-all duration-300',
              tenantsCollapsed ? 'pointer-events-none opacity-0' : 'opacity-100',
            ].join(' ')}
          >
            <TenantList 
              selectedTenantId={selectedTenantId} 
              reloadSignal={tenantReloadSignal}
            />
          </div>
        </section>

        <div className="flex min-w-0 flex-1 flex-col gap-4 h-full">
          <section className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex h-full min-h-0 flex-1 overflow-auto">
              <FinanceBox tenantId={selectedTenantId} />
            </div>
          </section>

          <section className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex h-full min-h-0 flex-1 overflow-auto">
              <OneDriveBox tenantId={selectedTenantId} />
            </div>
          </section>
        </div>

        <section className="flex min-w-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="h-full w-full min-h-0 overflow-hidden">
            <ThreadView tenantId={selectedTenantId} reloadSignal={tenantReloadSignal} />
          </div>
        </section>
      </div>

      <ImportModal
        open={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        onImported={() => setTenantReloadSignal((current) => current + 1)}
      />
    </main>
  )
}
