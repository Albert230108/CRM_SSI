import { useCallback, useEffect, useState } from 'react'
import { getUserPreferenceKey } from './dashboardLayoutPreferences'
import { useAuthStore } from '../store/authStore'

const STORAGE_PREFIX = 'crm_ssi.display-preferences.'

export type DisplayPreferences = {
  relativeTimestamps: boolean
}

const DEFAULT_PREFERENCES: DisplayPreferences = {
  relativeTimestamps: false,
}

function storageKeyFor(userKey: string): string {
  return `${STORAGE_PREFIX}${userKey}`
}

export function loadDisplayPreferences(userKey: string): DisplayPreferences {
  try {
    const raw = window.localStorage.getItem(storageKeyFor(userKey))
    if (!raw) return DEFAULT_PREFERENCES
    const parsed = JSON.parse(raw)
    return {
      relativeTimestamps: typeof parsed?.relativeTimestamps === 'boolean' ? parsed.relativeTimestamps : DEFAULT_PREFERENCES.relativeTimestamps,
    }
  } catch {
    return DEFAULT_PREFERENCES
  }
}

export function saveDisplayPreferences(userKey: string, preferences: DisplayPreferences): void {
  try {
    window.localStorage.setItem(storageKeyFor(userKey), JSON.stringify(preferences))
  } catch {
    // Storage may be unavailable (private browsing, quota exceeded, etc). Keep using the in-memory preference.
  }
}

/** Per-user "show relative timestamps" toggle, backed by localStorage. Falls back to absolute-time display when no user is signed in. */
export function useRelativeTimestampsPreference(): [boolean, (value: boolean) => void] {
  const user = useAuthStore((state) => state.user)
  const userKey = getUserPreferenceKey(user)
  const [relativeTimestamps, setRelativeTimestamps] = useState(false)

  useEffect(() => {
    setRelativeTimestamps(userKey ? loadDisplayPreferences(userKey).relativeTimestamps : false)
  }, [userKey])

  const update = useCallback(
    (value: boolean) => {
      setRelativeTimestamps(value)
      if (userKey) saveDisplayPreferences(userKey, { relativeTimestamps: value })
    },
    [userKey],
  )

  return [relativeTimestamps, update]
}
