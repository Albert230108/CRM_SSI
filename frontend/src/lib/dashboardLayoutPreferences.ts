export const LAYOUT_VERSION = 1

export const TENANT_SIDEBAR_MIN_WIDTH = 220
export const TENANT_SIDEBAR_MAX_WIDTH = 480
export const TENANT_SIDEBAR_DEFAULT_WIDTH = 260

export const MIDDLE_COLUMN_MIN_WIDTH = 320
export const RIGHT_PANEL_MIN_WIDTH = 360

export const DIVIDER_WIDTH = 10

export type DashboardLayoutPreference = {
  version: 1
  tenantSidebarExpandedWidth: number
  /** null means "no explicit preference" -> default 50/50 split with the right panel. */
  middleColumnWidth: number | null
}

const STORAGE_PREFIX = 'crm_ssi.dashboard.column-layout.'

type StableUser = { id?: number | string | null; email?: string | null } | null | undefined

export function getUserPreferenceKey(user: StableUser): string | null {
  if (!user) return null
  if (user.id !== null && user.id !== undefined && user.id !== '') {
    return String(user.id)
  }
  if (user.email) {
    return user.email.trim().toLowerCase()
  }
  return null
}

export function storageKeyFor(userKey: string): string {
  return `${STORAGE_PREFIX}${userKey}`
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function clampTenantSidebarWidth(width: number, containerWidth: number): number {
  const maxAllowed = Math.min(
    TENANT_SIDEBAR_MAX_WIDTH,
    Math.max(TENANT_SIDEBAR_MIN_WIDTH, containerWidth - DIVIDER_WIDTH * 2 - MIDDLE_COLUMN_MIN_WIDTH - RIGHT_PANEL_MIN_WIDTH),
  )
  return Math.min(Math.max(width, TENANT_SIDEBAR_MIN_WIDTH), maxAllowed)
}

export function clampMiddleColumnWidth(
  width: number,
  containerWidth: number,
  tenantSidebarWidth: number,
): number {
  const maxAllowed = Math.max(
    MIDDLE_COLUMN_MIN_WIDTH,
    containerWidth - DIVIDER_WIDTH * 2 - tenantSidebarWidth - RIGHT_PANEL_MIN_WIDTH,
  )
  return Math.min(Math.max(width, MIDDLE_COLUMN_MIN_WIDTH), maxAllowed)
}

/** Validates the shape/version/numeric values of a parsed preference blob. Returns null when invalid. */
export function validateStoredLayout(data: unknown): DashboardLayoutPreference | null {
  if (!data || typeof data !== 'object') return null
  const candidate = data as Record<string, unknown>
  if (candidate.version !== LAYOUT_VERSION) return null
  if (!isFiniteNumber(candidate.tenantSidebarExpandedWidth)) return null
  const middleColumnWidth = candidate.middleColumnWidth
  if (middleColumnWidth !== null && !isFiniteNumber(middleColumnWidth)) return null

  return {
    version: LAYOUT_VERSION,
    tenantSidebarExpandedWidth: candidate.tenantSidebarExpandedWidth,
    middleColumnWidth: middleColumnWidth === null ? null : (middleColumnWidth as number),
  }
}

export function loadDashboardLayoutPreference(userKey: string): DashboardLayoutPreference | null {
  try {
    const raw = window.localStorage.getItem(storageKeyFor(userKey))
    if (!raw) return null
    return validateStoredLayout(JSON.parse(raw))
  } catch {
    return null
  }
}

export function saveDashboardLayoutPreference(userKey: string, preference: DashboardLayoutPreference): void {
  try {
    window.localStorage.setItem(storageKeyFor(userKey), JSON.stringify(preference))
  } catch {
    // Storage may be unavailable (private browsing, quota exceeded, etc). Keep using the in-memory layout.
  }
}
