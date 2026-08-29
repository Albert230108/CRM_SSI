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

const SEARCH_ALL_TENANTS_PREFIX = 'crm_ssi.search-all-tenants.'

function searchAllTenantsKeyFor(userKey: string): string {
  return `${SEARCH_ALL_TENANTS_PREFIX}${userKey}`
}

export function loadSearchAllTenantsPreference(userKey: string): boolean {
  try {
    return window.localStorage.getItem(searchAllTenantsKeyFor(userKey)) === 'true'
  } catch {
    return false
  }
}

export function saveSearchAllTenantsPreference(userKey: string, value: boolean): void {
  try {
    window.localStorage.setItem(searchAllTenantsKeyFor(userKey), value ? 'true' : 'false')
  } catch {
    // Storage may be unavailable (private browsing, quota exceeded, etc). Keep using the in-memory value.
  }
}

/** Per-user "search all tenants" toggle in the tenant list, backed by localStorage. Falls back to off when no user is signed in. */
export function useSearchAllTenantsPreference(): [boolean, (value: boolean) => void] {
  const user = useAuthStore((state) => state.user)
  const userKey = getUserPreferenceKey(user)
  const [searchAllTenants, setSearchAllTenants] = useState(false)

  useEffect(() => {
    setSearchAllTenants(userKey ? loadSearchAllTenantsPreference(userKey) : false)
  }, [userKey])

  const update = useCallback(
    (value: boolean) => {
      setSearchAllTenants(value)
      if (userKey) saveSearchAllTenantsPreference(userKey, value)
    },
    [userKey],
  )

  return [searchAllTenants, update]
}

const SOUND_EFFECTS_PREFIX = 'crm_ssi.sound-effects.'

function soundEnabledKeyFor(userKey: string): string {
  return `${SOUND_EFFECTS_PREFIX}${userKey}`
}

export function loadSoundEnabledPreference(userKey: string): boolean {
  try {
    return window.localStorage.getItem(soundEnabledKeyFor(userKey)) === 'true'
  } catch {
    return false
  }
}

export function saveSoundEnabledPreference(userKey: string, value: boolean): void {
  try {
    window.localStorage.setItem(soundEnabledKeyFor(userKey), value ? 'true' : 'false')
  } catch {
    // Storage may be unavailable (private browsing, quota exceeded, etc). Keep using the in-memory value.
  }
}

/** Per-user "play sound effects" toggle, backed by localStorage. Falls back to off when no user is signed in. */
export function useSoundEnabledPreference(): [boolean, (value: boolean) => void] {
  const user = useAuthStore((state) => state.user)
  const userKey = getUserPreferenceKey(user)
  const [soundEnabled, setSoundEnabled] = useState(false)

  useEffect(() => {
    setSoundEnabled(userKey ? loadSoundEnabledPreference(userKey) : false)
  }, [userKey])

  const update = useCallback(
    (value: boolean) => {
      setSoundEnabled(value)
      if (userKey) saveSoundEnabledPreference(userKey, value)
    },
    [userKey],
  )

  return [soundEnabled, update]
}
