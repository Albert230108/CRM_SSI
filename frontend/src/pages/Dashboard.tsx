import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import ColumnResizeHandle from '../components/ColumnResizeHandle'
import FinanceBox from '../components/FinanceBox'
import NotesBox from '../components/NotesBox'
import OneDriveBox from '../components/OneDriveBox'
import TenantList from '../components/TenantList'
import ThreadView from '../components/ThreadView'
import ToastCard from '../components/ToastCard'
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
import { useNotesDraftStore } from '../store/notesDraftStore'
import { useSyncStore } from '../store/syncStore'

const DESKTOP_BREAKPOINT = '(min-width: 768px)'
const MESSAGE_TOAST_DURATION_MS = 6000

type MessageToast = {
  id: number
  text: string
}

export default function Dashboard() {
  const user = useAuthStore((state) => state.user)
  const { tenantId } = useParams()
  const selectedTenantId = useMemo(() => {
    const parsed = Number(tenantId)
    return Number.isFinite(parsed) ? parsed : undefined
  }, [tenantId])

  // Populated from the notification-click URL (?channel=&thread_ref=), then stripped from the
  // URL so switching tenants and coming back doesn't keep re-opening the same thread. Dashboard
  // stays mounted across notification-driven navigation (only the tenantId route param and these
  // search params change), so this has to react to searchParams changing -- a one-time lazy
  // useState initializer would only fire on Dashboard's first-ever mount and miss every
  // subsequent notification click.
  const [searchParams, setSearchParams] = useSearchParams()
  const [initialThreadTarget, setInitialThreadTarget] = useState<{ channel: string; threadRef: string } | null>(null)
  useEffect(() => {
    const channel = searchParams.get('channel')
    const threadRef = searchParams.get('thread_ref')
    if (!channel || !threadRef) return
    setInitialThreadTarget({ channel, threadRef })
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.delete('channel')
      next.delete('thread_ref')
      return next
    }, { replace: true })
  }, [searchParams, setSearchParams])

  // Tracks whether each of the finance/OneDrive/thread tiles has finished loading data for
  // the currently selected tenant, so all three can stay blurred together until every tile
  // is ready (rather than un-blurring independently as each fetch resolves).
  const [financeReady, setFinanceReady] = useState(false)
  const [oneDriveReady, setOneDriveReady] = useState(false)
  const [notesReady, setNotesReady] = useState(false)
  const [threadReady, setThreadReady] = useState(false)
  const selectedTenantIdRef = useRef(selectedTenantId)

  useEffect(() => {
    selectedTenantIdRef.current = selectedTenantId
  }, [selectedTenantId])

  // Native browsers can't show custom confirm text on tab close/refresh, so this best-effort
  // flushes the in-progress notes edit as a draft (so it survives) and still shows the
  // browser's own "leave site" prompt.
  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      const { isDirty, handlers } = useNotesDraftStore.getState()
      if (!isDirty) return
      handlers?.flushDraft()
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [])

  useEffect(() => {
    setFinanceReady(false)
    setOneDriveReady(false)
    setNotesReady(false)
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
  const handleNotesReady = useCallback((readyTenantId: number) => {
    if (readyTenantId === selectedTenantIdRef.current) setNotesReady(true)
  }, [])

  const handleThreadReady = useCallback((readyTenantId: number) => {
    if (readyTenantId === selectedTenantIdRef.current) setThreadReady(true)
  }, [])

  const isSwitchingTenant = selectedTenantId !== undefined && !(financeReady && oneDriveReady && notesReady && threadReady)

  const [tenantsCollapsed, setTenantsCollapsed] = useState(false)
  const [middleColumnCollapsed, setMiddleColumnCollapsed] = useState(false)
  const [tenantReloadSignal, setTenantReloadSignal] = useState(0)
  const [messageToasts, setMessageToasts] = useState<MessageToast[]>([])
  const messageToastIdRef = useRef(0)

  const syncCompletedAt = useSyncStore((state) => state.syncCompletedAt)
  const importCompletedAt = useSyncStore((state) => state.importCompletedAt)
  const reloadWatermarkRef = useRef({ sync: syncCompletedAt, import: importCompletedAt })
  useEffect(() => {
    const watermark = reloadWatermarkRef.current
    if (syncCompletedAt === watermark.sync && importCompletedAt === watermark.import) return
    reloadWatermarkRef.current = { sync: syncCompletedAt, import: importCompletedAt }
    setTenantReloadSignal((current) => current + 1)
  }, [syncCompletedAt, importCompletedAt])

  const handleNewMessage = useCallback(({ tenantName, channel }: { tenantName: string; channel: string; direction: string }) => {
    const id = ++messageToastIdRef.current
    const channelLabel = channel.toLowerCase() === 'whatsapp' ? 'WhatsApp message' : channel.toLowerCase() === 'email' ? 'email' : channel
    setMessageToasts((current) => [...current, { id, text: `New ${channelLabel} from ${tenantName}` }])
    window.setTimeout(() => {
      setMessageToasts((current) => current.filter((toast) => toast.id !== id))
    }, MESSAGE_TOAST_DURATION_MS)
  }, [])

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

  const middleColumnMaxWidth = Math.max(
    MIDDLE_COLUMN_MIN_WIDTH,
    containerWidth - DIVIDER_WIDTH * 2 - tenantSidebarWidth - RIGHT_PANEL_MIN_WIDTH,
  )
  // Tracks whether the user's last explicit drag pinned the middle column to its
  // max available width, so it keeps growing to fill the space on later resizes
  // instead of staying stuck at the pixel value captured at drag time.
  const middleColumnPinnedToMaxRef = useRef(false)

  const effectiveMiddleWidth =
    middleColumnWidth ?? Math.max(MIDDLE_COLUMN_MIN_WIDTH, (containerWidth - DIVIDER_WIDTH * 2 - tenantSidebarWidth) / 2)

  // Re-clamp (or, if the user previously maximized it, re-grow) an explicitly-set
  // middle width whenever the available space changes (window resize, sidebar
  // collapse/expand, other divider drag).
  useEffect(() => {
    setMiddleColumnWidth((current) => {
      if (current === null) return current
      if (middleColumnPinnedToMaxRef.current) return middleColumnMaxWidth
      const clamped = clampMiddleColumnWidth(current, containerWidth, tenantSidebarWidth)
      return clamped === current ? current : clamped
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerWidth, tenantSidebarWidth, middleColumnMaxWidth])

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
      middleColumnPinnedToMaxRef.current = current !== null && current >= middleColumnMaxWidth
      persistLayout(tenantSidebarWidth, current)
      return current
    })
  }

  return (
    <main className="flex h-full w-full flex-col overflow-hidden px-3 py-2">
      <div className="fixed right-4 top-4 z-50 flex flex-col gap-2">
        {messageToasts.map((toast) => (
          <ToastCard key={toast.id} toastKey={toast.id} tone="info" durationMs={MESSAGE_TOAST_DURATION_MS}>
            <p className="font-medium">{toast.text}</p>
          </ToastCard>
        ))}
      </div>

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
              'h-full w-full min-w-0 overflow-hidden p-1.5 transition-all duration-300',
              tenantsCollapsed ? 'pointer-events-none opacity-0' : 'opacity-100',
            ].join(' ')}
          >
            <TenantList
              selectedTenantId={selectedTenantId}
              reloadSignal={tenantReloadSignal}
              onNewMessage={handleNewMessage}
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
              'h-full w-full min-w-0 overflow-hidden p-1.5 transition-all duration-300 flex flex-col gap-1.5',
              middleColumnCollapsed ? 'pointer-events-none opacity-0' : 'opacity-100',
            ].join(' ')}
          >
            <section className="relative flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-1.5 shadow-sm">
              <div className="flex h-full min-h-0 w-full flex-1 flex-col overflow-auto">
                <FinanceBox tenantId={selectedTenantId} onReady={handleFinanceReady} />
              </div>
              <TileLoadingOverlay active={isSwitchingTenant} />
            </section>

            <div className="flex min-h-0 flex-1 flex-col gap-1.5">
              <section className="relative flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-1.5 shadow-sm">
                <div className="flex h-full min-h-0 w-full flex-1 flex-col overflow-auto">
                  <NotesBox tenantId={selectedTenantId} onReady={handleNotesReady} />
                </div>
                <TileLoadingOverlay active={isSwitchingTenant} />
              </section>

              <section className="relative flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-1.5 shadow-sm">
                <div className="flex h-full min-h-0 w-full flex-1 flex-col overflow-auto">
                  <OneDriveBox tenantId={selectedTenantId} onReady={handleOneDriveReady} />
                </div>
                <TileLoadingOverlay active={isSwitchingTenant} />
              </section>
            </div>
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
          className="relative flex flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm transition-all duration-300"
          style={{ minWidth: RIGHT_PANEL_MIN_WIDTH }}
        >
          <div className="h-full w-full min-h-0 overflow-hidden">
            <ThreadView
              tenantId={selectedTenantId}
              reloadSignal={tenantReloadSignal}
              onReady={handleThreadReady}
              initialThreadTarget={initialThreadTarget}
              onInitialThreadTargetConsumed={() => setInitialThreadTarget(null)}
            />
          </div>
          <TileLoadingOverlay active={isSwitchingTenant} />
        </section>
      </div>
    </main>
  )
}
