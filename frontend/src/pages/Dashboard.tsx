import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import ColumnResizeHandle from '../components/ColumnResizeHandle'
import FinanceBox from '../components/FinanceBox'
import ImportModal from '../components/ImportModal'
import OneDriveBox from '../components/OneDriveBox'
import TenantList from '../components/TenantList'
import ThreadView from '../components/ThreadView'
import TileLoadingOverlay from '../components/TileLoadingOverlay'
import {
  clampMiddleColumnWidth,
  clampTenantSidebarWidth,
  DIVIDER_WIDTH,
  getUserPreferenceKey,
  loadDashboardLayoutPreference,
  MIDDLE_COLUMN_MIN_WIDTH,
  RIGHT_PANEL_MIN_WIDTH,
  saveDashboardLayoutPreference,
  TENANT_SIDEBAR_DEFAULT_WIDTH,
  TENANT_SIDEBAR_MAX_WIDTH,
  TENANT_SIDEBAR_MIN_WIDTH,
} from '../lib/dashboardLayoutPreferences'
import { useAuthStore } from '../store/authStore'

const DESKTOP_BREAKPOINT = '(min-width: 768px)'

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
  const user = useAuthStore((state) => state.user)
  const { tenantId } = useParams()
  const selectedTenantId = useMemo(() => {
    const parsed = Number(tenantId)
    return Number.isFinite(parsed) ? parsed : undefined
  }, [tenantId])

  // Tracks whether each of the finance/OneDrive/thread tiles has finished loading data for
  // the currently selected tenant, so all three can stay blurred together until every tile
  // is ready (rather than un-blurring independently as each fetch resolves).
  const [financeReady, setFinanceReady] = useState(false)
  const [oneDriveReady, setOneDriveReady] = useState(false)
  const [threadReady, setThreadReady] = useState(false)
  const selectedTenantIdRef = useRef(selectedTenantId)

  useEffect(() => {
    selectedTenantIdRef.current = selectedTenantId
  }, [selectedTenantId])

  useEffect(() => {
    setFinanceReady(false)
    setOneDriveReady(false)
    setThreadReady(false)
  }, [selectedTenantId])

  // Stable callback identities (empty deps) so passing them down doesn't retrigger the
  // tiles' own data-fetching effects; staleness is avoided via selectedTenantIdRef.
  const handleFinanceReady = useCallback((readyTenantId: number) => {
    if (readyTenantId === selectedTenantIdRef.current) setFinanceReady(true)
  }, [])
  const handleOneDriveReady = useCallback((readyTenantId: number) => {
    if (readyTenantId === selectedTenantIdRef.current) setOneDriveReady(true)
  }, [])
  const handleThreadReady = useCallback((readyTenantId: number) => {
    if (readyTenantId === selectedTenantIdRef.current) setThreadReady(true)
  }, [])

  const isSwitchingTenant = selectedTenantId !== undefined && !(financeReady && oneDriveReady && threadReady)

  const [importModalOpen, setImportModalOpen] = useState(false)
  const [tenantsCollapsed, setTenantsCollapsed] = useState(false)
  const [middleColumnCollapsed, setMiddleColumnCollapsed] = useState(false)
  const [tenantReloadSignal, setTenantReloadSignal] = useState(0)
  const [syncRunning, setSyncRunning] = useState(false)
  const [syncSummary, setSyncSummary] = useState<SyncSummary | null>(null)
  const [syncError, setSyncError] = useState('')
  const [syncToken, setSyncToken] = useState(0)
  const [toastVisible, setToastVisible] = useState(false)

  const columnsContainerRef = useRef<HTMLDivElement | null>(null)
  const [containerWidth, setContainerWidth] = useState(1200)
  const [isDesktop, setIsDesktop] = useState(true)
  const [tenantSidebarWidth, setTenantSidebarWidth] = useState(TENANT_SIDEBAR_DEFAULT_WIDTH)
  // null = no explicit preference yet -> default 50/50 split between middle and right panels.
  const [middleColumnWidth, setMiddleColumnWidth] = useState<number | null>(null)
  const dragBaseWidthRef = useRef(0)

  const userPreferenceKey = getUserPreferenceKey(user)

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 767px)')
    const updateCollapsedState = () => setTenantsCollapsed(mediaQuery.matches)

    updateCollapsedState()
    mediaQuery.addEventListener('change', updateCollapsedState)
    return () => mediaQuery.removeEventListener('change', updateCollapsedState)
  }, [])

  useEffect(() => {
    const mediaQuery = window.matchMedia(DESKTOP_BREAKPOINT)
    const updateDesktopState = () => setIsDesktop(mediaQuery.matches)

    updateDesktopState()
    mediaQuery.addEventListener('change', updateDesktopState)
    return () => mediaQuery.removeEventListener('change', updateDesktopState)
  }, [])

  useEffect(() => {
    const element = columnsContainerRef.current
    if (!element || typeof ResizeObserver === 'undefined') return

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width) setContainerWidth(width)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // Load this user's saved column layout whenever the authenticated user changes.
  useEffect(() => {
    if (!userPreferenceKey) {
      setTenantSidebarWidth(TENANT_SIDEBAR_DEFAULT_WIDTH)
      setMiddleColumnWidth(null)
      return
    }
    const saved = loadDashboardLayoutPreference(userPreferenceKey)
    if (!saved) {
      setTenantSidebarWidth(TENANT_SIDEBAR_DEFAULT_WIDTH)
      setMiddleColumnWidth(null)
      return
    }
    setTenantSidebarWidth(clampTenantSidebarWidth(saved.tenantSidebarExpandedWidth, containerWidth))
    setMiddleColumnWidth(
      saved.middleColumnWidth === null
        ? null
        : clampMiddleColumnWidth(saved.middleColumnWidth, containerWidth, saved.tenantSidebarExpandedWidth),
    )
    // Re-run only when the user identity changes; containerWidth is read at load time only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userPreferenceKey])

  const persistLayout = (nextTenantWidth: number, nextMiddleWidth: number | null) => {
    if (!userPreferenceKey) return
    saveDashboardLayoutPreference(userPreferenceKey, {
      version: 1,
      tenantSidebarExpandedWidth: nextTenantWidth,
      middleColumnWidth: nextMiddleWidth,
    })
  }

  const effectiveMiddleWidth =
    middleColumnWidth ?? Math.max(MIDDLE_COLUMN_MIN_WIDTH, (containerWidth - DIVIDER_WIDTH * 2 - tenantSidebarWidth) / 2)

  const handleTenantDividerStart = () => {
    dragBaseWidthRef.current = tenantSidebarWidth
  }
  const handleTenantDividerAdjust = (deltaPx: number) => {
    setTenantSidebarWidth(clampTenantSidebarWidth(dragBaseWidthRef.current + deltaPx, containerWidth))
  }
  const handleTenantDividerEnd = () => {
    setTenantSidebarWidth((current) => {
      persistLayout(current, middleColumnWidth)
      return current
    })
  }

  const handleMiddleDividerStart = () => {
    dragBaseWidthRef.current = effectiveMiddleWidth
  }
  const handleMiddleDividerAdjust = (deltaPx: number) => {
    setMiddleColumnWidth(clampMiddleColumnWidth(dragBaseWidthRef.current + deltaPx, containerWidth, tenantSidebarWidth))
  }
  const handleMiddleDividerEnd = () => {
    setMiddleColumnWidth((current) => {
      persistLayout(tenantSidebarWidth, current)
      return current
    })
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
          setTenantReloadSignal((current) => current + 1)
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
  }, [syncSummary?.whatsapp_sync_queued, token])

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
      setSyncToken((current) => current + 1)
    }
  }

  return (
    <main className="flex h-full w-full flex-col overflow-hidden px-4 py-4">
      <div className="mb-3 flex w-full items-center justify-between gap-4">
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

      {toastVisible && (syncSummary || syncError) ? (
        <div
          className={[
            'fixed right-4 top-4 z-50 w-80 overflow-hidden rounded-2xl border shadow-lg',
            syncError ? 'border-rose-200 bg-rose-50 text-rose-900' : 'border-emerald-200 bg-emerald-50 text-emerald-900',
          ].join(' ')}
        >
          <div className="px-4 py-3 text-sm">
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
          </div>
          <div className={['h-1 w-full', syncError ? 'bg-rose-200' : 'bg-emerald-200'].join(' ')}>
            <div
              key={syncToken}
              className={['h-full animate-toast-countdown', syncError ? 'bg-rose-500' : 'bg-emerald-500'].join(' ')}
            />
          </div>
        </div>
      ) : null}

      <div ref={columnsContainerRef} className="flex flex-row flex-1 min-h-0 overflow-hidden">
        <section
          className={[
            'relative flex h-full shrink-0 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm',
            tenantsCollapsed ? 'w-10 transition-all duration-300' : '',
          ].join(' ')}
          style={tenantsCollapsed ? undefined : { width: tenantSidebarWidth }}
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
              'h-full min-w-0 overflow-hidden p-3 transition-all duration-300',
              tenantsCollapsed ? 'pointer-events-none opacity-0' : 'opacity-100',
            ].join(' ')}
          >
            <TenantList
              selectedTenantId={selectedTenantId}
              reloadSignal={tenantReloadSignal}
            />
          </div>
        </section>

        <ColumnResizeHandle
          label="Resize tenant sidebar"
          disabled={!isDesktop || tenantsCollapsed}
          valueNow={tenantSidebarWidth}
          valueMin={TENANT_SIDEBAR_MIN_WIDTH}
          valueMax={TENANT_SIDEBAR_MAX_WIDTH}
          onAdjustStart={handleTenantDividerStart}
          onAdjust={handleTenantDividerAdjust}
          onAdjustEnd={handleTenantDividerEnd}
        />

        <section
          className={[
            'relative flex h-full overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm',
            middleColumnCollapsed ? 'w-10 shrink-0 transition-all duration-300' : 'min-w-0',
          ].join(' ')}
          style={middleColumnCollapsed ? undefined : { width: effectiveMiddleWidth, flexShrink: 0 }}
        >
          <button
            type="button"
            onClick={() => setMiddleColumnCollapsed((current) => !current)}
            aria-label={middleColumnCollapsed ? 'Expand middle panel' : 'Collapse middle panel'}
            className="absolute right-0 top-4 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-l-xl border border-gray-200 border-r-0 bg-white text-sm font-semibold text-gray-600 shadow-sm transition hover:bg-gray-50"
          >
            {middleColumnCollapsed ? '◀' : '▶'}
          </button>
          <div
            className={[
              'h-full min-w-0 overflow-hidden p-3 transition-all duration-300 flex flex-col gap-3',
              middleColumnCollapsed ? 'pointer-events-none opacity-0' : 'opacity-100',
            ].join(' ')}
          >
            <section className="relative flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
              <div className="flex h-full min-h-0 flex-1 overflow-auto">
                <FinanceBox tenantId={selectedTenantId} onReady={handleFinanceReady} />
              </div>
              <TileLoadingOverlay active={isSwitchingTenant} />
            </section>

            <section className="relative flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
              <div className="flex h-full min-h-0 flex-1 overflow-auto">
                <OneDriveBox tenantId={selectedTenantId} onReady={handleOneDriveReady} />
              </div>
              <TileLoadingOverlay active={isSwitchingTenant} />
            </section>
          </div>
        </section>

        <ColumnResizeHandle
          label="Resize thread panel"
          disabled={!isDesktop || middleColumnCollapsed}
          valueNow={effectiveMiddleWidth}
          valueMin={MIDDLE_COLUMN_MIN_WIDTH}
          valueMax={Math.max(
            MIDDLE_COLUMN_MIN_WIDTH,
            containerWidth - DIVIDER_WIDTH * 2 - tenantSidebarWidth - RIGHT_PANEL_MIN_WIDTH,
          )}
          onAdjustStart={handleMiddleDividerStart}
          onAdjust={handleMiddleDividerAdjust}
          onAdjustEnd={handleMiddleDividerEnd}
        />

        <section
          className="relative flex flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-3 shadow-sm transition-all duration-300"
          style={{ minWidth: RIGHT_PANEL_MIN_WIDTH }}
        >
          <div className="h-full w-full min-h-0 overflow-hidden">
            <ThreadView tenantId={selectedTenantId} reloadSignal={tenantReloadSignal} onReady={handleThreadReady} />
          </div>
          <TileLoadingOverlay active={isSwitchingTenant} />
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
