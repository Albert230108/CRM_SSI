const DIAG_LOG_KEY = 'crm_diag_log'
const DIAG_LOG_LIMIT = 200

type DiagEntry = {
  t: string
  tabId: string
  event: string
  detail?: unknown
}

let installed = false
const tabId = createTabId()

function createTabId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
}

function readDiagLog(): DiagEntry[] {
  try {
    const raw = localStorage.getItem(DIAG_LOG_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as DiagEntry[]) : []
  } catch {
    return []
  }
}

function writeDiagLog(entries: DiagEntry[]) {
  try {
    localStorage.setItem(DIAG_LOG_KEY, JSON.stringify(entries.slice(-DIAG_LOG_LIMIT)))
  } catch {
    // Best-effort diagnostics only.
  }
}

export function logDiag(event: string, detail?: unknown) {
  const entry: DiagEntry = {
    t: new Date().toISOString(),
    tabId,
    event,
  }

  if (detail !== undefined) {
    entry.detail = detail
  }

  const entries = readDiagLog()
  entries.push(entry)
  writeDiagLog(entries)
}

export function installRefreshDiagnostics() {
  if (installed) return
  installed = true

  window.__dumpDiagLog = () => {
    try {
      const entries = readDiagLog()
      console.table(entries)
      return entries
    } catch {
      console.table([])
      return []
    }
  }

  const getNavigationType = () => {
    try {
      const navigationEntry = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
      return navigationEntry?.type ?? null
    } catch {
      return null
    }
  }

  const beforeUnloadHandler = () => {
    logDiag('beforeunload', {
      visibilityState: document.visibilityState,
      navigationType: getNavigationType(),
    })
  }

  const visibilityHandler = () => {
    logDiag('visibilitychange', {
      visibilityState: document.visibilityState,
    })
  }

  window.addEventListener('beforeunload', beforeUnloadHandler)
  document.addEventListener('visibilitychange', visibilityHandler)
}
