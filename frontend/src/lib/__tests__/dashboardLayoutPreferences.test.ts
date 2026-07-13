import { describe, it, expect, beforeEach } from 'vitest'
import {
  clampMiddleColumnWidth,
  clampTenantSidebarWidth,
  getUserPreferenceKey,
  loadDashboardLayoutPreference,
  MIDDLE_COLUMN_MIN_WIDTH,
  RIGHT_PANEL_MIN_WIDTH,
  saveDashboardLayoutPreference,
  storageKeyFor,
  TENANT_SIDEBAR_DEFAULT_WIDTH,
  TENANT_SIDEBAR_MAX_WIDTH,
  TENANT_SIDEBAR_MIN_WIDTH,
  validateStoredLayout,
} from '../dashboardLayoutPreferences'

describe('getUserPreferenceKey', () => {
  it('prefers the numeric user id', () => {
    expect(getUserPreferenceKey({ id: 42, email: 'a@example.com' })).toBe('42')
  })

  it('falls back to a normalized email when id is missing', () => {
    expect(getUserPreferenceKey({ email: '  User@Example.com  '.trim() })).toBe('user@example.com')
  })

  it('returns null when neither id nor email is available', () => {
    expect(getUserPreferenceKey(null)).toBeNull()
    expect(getUserPreferenceKey({})).toBeNull()
  })
})

describe('clampTenantSidebarWidth', () => {
  it('clamps below the minimum', () => {
    expect(clampTenantSidebarWidth(10, 1200)).toBe(TENANT_SIDEBAR_MIN_WIDTH)
  })

  it('clamps above the maximum', () => {
    expect(clampTenantSidebarWidth(10000, 1200)).toBe(TENANT_SIDEBAR_MAX_WIDTH)
  })

  it('shrinks the max when the container is too narrow to fit the other panels', () => {
    const narrowContainerWidth = 700
    const result = clampTenantSidebarWidth(TENANT_SIDEBAR_MAX_WIDTH, narrowContainerWidth)
    expect(result).toBeLessThan(TENANT_SIDEBAR_MAX_WIDTH)
    expect(result).toBeGreaterThanOrEqual(TENANT_SIDEBAR_MIN_WIDTH)
  })

  it('passes through valid values unchanged', () => {
    expect(clampTenantSidebarWidth(300, 1400)).toBe(300)
  })
})

describe('clampMiddleColumnWidth', () => {
  it('clamps below the minimum', () => {
    expect(clampMiddleColumnWidth(10, 1400, TENANT_SIDEBAR_DEFAULT_WIDTH)).toBe(MIDDLE_COLUMN_MIN_WIDTH)
  })

  it('never leaves less than the right panel minimum in a narrow container', () => {
    const containerWidth = 900
    const result = clampMiddleColumnWidth(5000, containerWidth, TENANT_SIDEBAR_DEFAULT_WIDTH)
    const remainingForRight = containerWidth - 32 - TENANT_SIDEBAR_DEFAULT_WIDTH - result
    expect(remainingForRight).toBeGreaterThanOrEqual(0)
  })

  it('passes through valid values unchanged', () => {
    expect(clampMiddleColumnWidth(500, 1600, TENANT_SIDEBAR_DEFAULT_WIDTH)).toBe(500)
  })
})

describe('validateStoredLayout', () => {
  it('accepts a well-formed payload', () => {
    const result = validateStoredLayout({ version: 1, tenantSidebarExpandedWidth: 300, middleColumnWidth: 500 })
    expect(result).toEqual({ version: 1, tenantSidebarExpandedWidth: 300, middleColumnWidth: 500 })
  })

  it('accepts a null middleColumnWidth (no explicit preference)', () => {
    const result = validateStoredLayout({ version: 1, tenantSidebarExpandedWidth: 300, middleColumnWidth: null })
    expect(result?.middleColumnWidth).toBeNull()
  })

  it('rejects a mismatched version', () => {
    expect(validateStoredLayout({ version: 2, tenantSidebarExpandedWidth: 300, middleColumnWidth: null })).toBeNull()
  })

  it('rejects non-numeric widths', () => {
    expect(validateStoredLayout({ version: 1, tenantSidebarExpandedWidth: 'wide', middleColumnWidth: null })).toBeNull()
  })

  it('rejects NaN/Infinity widths', () => {
    expect(validateStoredLayout({ version: 1, tenantSidebarExpandedWidth: NaN, middleColumnWidth: null })).toBeNull()
    expect(validateStoredLayout({ version: 1, tenantSidebarExpandedWidth: Infinity, middleColumnWidth: null })).toBeNull()
  })

  it('rejects null/non-object input', () => {
    expect(validateStoredLayout(null)).toBeNull()
    expect(validateStoredLayout('garbage')).toBeNull()
    expect(validateStoredLayout(42)).toBeNull()
  })
})

describe('load/save round-trip', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('returns null when nothing is stored', () => {
    expect(loadDashboardLayoutPreference('user-1')).toBeNull()
  })

  it('round-trips a saved preference scoped by user key', () => {
    saveDashboardLayoutPreference('user-1', { version: 1, tenantSidebarExpandedWidth: 320, middleColumnWidth: 480 })
    expect(loadDashboardLayoutPreference('user-1')).toEqual({
      version: 1,
      tenantSidebarExpandedWidth: 320,
      middleColumnWidth: 480,
    })
    expect(loadDashboardLayoutPreference('user-2')).toBeNull()
  })

  it('falls back safely when stored JSON is malformed', () => {
    window.localStorage.setItem(storageKeyFor('user-1'), '{not valid json')
    expect(loadDashboardLayoutPreference('user-1')).toBeNull()
  })

  it('falls back safely when the stored shape is invalid', () => {
    window.localStorage.setItem(storageKeyFor('user-1'), JSON.stringify({ foo: 'bar' }))
    expect(loadDashboardLayoutPreference('user-1')).toBeNull()
  })

  it('does not throw when localStorage.setItem fails', () => {
    const original = window.localStorage.setItem
    window.localStorage.setItem = () => {
      throw new Error('quota exceeded')
    }
    expect(() =>
      saveDashboardLayoutPreference('user-1', { version: 1, tenantSidebarExpandedWidth: 300, middleColumnWidth: null }),
    ).not.toThrow()
    window.localStorage.setItem = original
  })
})

it('right panel minimum constant is a sane positive number', () => {
  expect(RIGHT_PANEL_MIN_WIDTH).toBeGreaterThan(0)
})
