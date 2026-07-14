import { useCallback, useEffect, useState } from 'react'
import { getUserPreferenceKey } from './dashboardLayoutPreferences'
import { useAuthStore } from '../store/authStore'

const STORAGE_PREFIX = 'crm_ssi.display-preferences.'

export type DisplayPreferences = {
  /** When true, timestamps show as "Relative date (date time)" instead of the default "date time (relative date)". */
  relativeTimestampsFirst: boolean
}

const DEFAULT_PREFERENCES: DisplayPreferences = {
  relativeTimestampsFirst: false,
}

const LOCAL_FOLDER_ROOT_PATH_PREFIX = 'crm_ssi.local-folder-root-path.'

function localFolderRootPathKeyFor(userKey: string): string {
  return `${LOCAL_FOLDER_ROOT_PATH_PREFIX}${userKey}`
}

export function loadLocalFolderRootPath(userKey: string): string {
  try {
    return window.localStorage.getItem(localFolderRootPathKeyFor(userKey)) ?? ''
  } catch {
    return ''
  }
}

export function saveLocalFolderRootPath(userKey: string, path: string): void {
  try {
    window.localStorage.setItem(localFolderRootPathKeyFor(userKey), path)
  } catch {
    // Storage may be unavailable (private browsing, quota exceeded, etc). Keep using the in-memory value.
  }
}

/** Per-user absolute filesystem path matching the connected local folder, used to open tenant folders in the native file explorer. */
export function useLocalFolderRootPath(): [string, (value: string) => void] {
  const user = useAuthStore((state) => state.user)
  const userKey = getUserPreferenceKey(user)
  const [rootPath, setRootPath] = useState('')

  useEffect(() => {
    setRootPath(userKey ? loadLocalFolderRootPath(userKey) : '')
  }, [userKey])

  const update = useCallback(
    (value: string) => {
      setRootPath(value)
      if (userKey) saveLocalFolderRootPath(userKey, value)
    },
    [userKey],
  )

  return [rootPath, update]
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
      relativeTimestampsFirst:
        typeof parsed?.relativeTimestampsFirst === 'boolean' ? parsed.relativeTimestampsFirst : DEFAULT_PREFERENCES.relativeTimestampsFirst,
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

/** Per-user timestamp order toggle ("date time (relative)" by default, or "relative (date time)" when enabled), backed by localStorage. Falls back to the default order when no user is signed in. */
export function useRelativeTimestampsFirstPreference(): [boolean, (value: boolean) => void] {
  const user = useAuthStore((state) => state.user)
  const userKey = getUserPreferenceKey(user)
  const [relativeTimestampsFirst, setRelativeTimestampsFirst] = useState(false)

  useEffect(() => {
    setRelativeTimestampsFirst(userKey ? loadDisplayPreferences(userKey).relativeTimestampsFirst : false)
  }, [userKey])

  const update = useCallback(
    (value: boolean) => {
      setRelativeTimestampsFirst(value)
      if (userKey) saveDisplayPreferences(userKey, { relativeTimestampsFirst: value })
    },
    [userKey],
  )

  return [relativeTimestampsFirst, update]
}
