import { getUserPreferenceKey } from './dashboardLayoutPreferences'

export type BoxType = 'email-thread' | 'whatsapp-group' | 'whatsapp-block'

export type FloatingBoxSize = {
  version: 1
  width: number
  height: number
}

const STORAGE_PREFIX = 'crm_ssi.floating-box-size.'

function storageKeyFor(boxType: BoxType, userKey: string): string {
  return `${STORAGE_PREFIX}${boxType}.${userKey}`
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function validateStoredSize(data: unknown): FloatingBoxSize | null {
  if (!data || typeof data !== 'object') return null
  const candidate = data as Record<string, unknown>
  if (candidate.version !== 1) return null
  if (!isFiniteNumber(candidate.width)) return null
  if (!isFiniteNumber(candidate.height)) return null

  return {
    version: 1,
    width: candidate.width,
    height: candidate.height,
  }
}

export function loadFloatingBoxSize(boxType: BoxType, userKey: string | null): FloatingBoxSize | null {
  if (!userKey) return null
  try {
    const raw = window.localStorage.getItem(storageKeyFor(boxType, userKey))
    if (!raw) return null
    return validateStoredSize(JSON.parse(raw))
  } catch {
    return null
  }
}

export function saveFloatingBoxSize(boxType: BoxType, userKey: string | null, size: FloatingBoxSize): void {
  if (!userKey) return
  try {
    window.localStorage.setItem(storageKeyFor(boxType, userKey), JSON.stringify(size))
  } catch {
    // Storage may be unavailable (private browsing, quota exceeded, etc). Keep using the in-memory size.
  }
}

export function getUserKeyForFloatingBoxSize(user: { id?: number | string | null; email?: string | null } | null | undefined): string | null {
  return getUserPreferenceKey(user)
}
