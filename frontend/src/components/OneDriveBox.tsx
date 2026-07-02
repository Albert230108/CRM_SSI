import { useEffect, useMemo, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { clearDirectoryHandleForUser, getDirectoryHandleForUser, setDirectoryHandleForUser } from '../lib/fileHandleStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type TenantSummary = {
  id: number
  booking_id: string
  name?: string | null
  first_name?: string | null
  last_name?: string | null
}

type LocalFolderItem = {
  name: string
  kind: 'file' | 'directory'
  size?: number
  handle: FileSystemFileHandle | FileSystemDirectoryHandle
}

type OneDriveBoxProps = {
  tenantId?: number
}

export default function OneDriveBox({ tenantId }: OneDriveBoxProps) {
  const token = useAuthStore((state) => state.token)
  const userEmail = useAuthStore((state) => state.userEmail)
  const userKey = userEmail ?? 'anonymous'
  const [tenant, setTenant] = useState<TenantSummary | null>(null)
  const [rootHandle, setRootHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [yearHandle, setYearHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [tenantHandle, setTenantHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [items, setItems] = useState<LocalFolderItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [unsupported, setUnsupported] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [stagedHandle, setStagedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [permissionState, setPermissionState] = useState<'granted' | 'prompt' | 'denied' | null>(null)

  useEffect(() => {
    setUnsupported(typeof window === 'undefined' || typeof window.showDirectoryPicker !== 'function')
  }, [])

  useEffect(() => {
    if (!tenantId) {
      setTenant(null)
      setRootHandle(null)
      setYearHandle(null)
      setTenantHandle(null)
      setItems([])
      setError('')
      setLoading(false)
      return
    }

    const controller = new AbortController()
    const loadTenant = async () => {
      try {
        setLoading(true)
        setError('')
        const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('Failed to load tenant details')
        const data: TenantSummary = await response.json()
        setTenant(data)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load tenant details')
      } finally {
        setLoading(false)
      }
    }

    loadTenant()
    return () => controller.abort()
  }, [tenantId, token])

  const tenantBookingId = tenant?.booking_id?.trim() || ''

  const tenantDisplayName = useMemo(() => {
    if (!tenant) return ''
    const firstName = tenant.first_name?.trim() || ''
    const lastName = tenant.last_name?.trim() || ''
    const combinedName = [firstName, lastName].filter(Boolean).join(' ').trim()
    if (combinedName) return combinedName
    return tenant.name?.trim() || ''
  }, [tenant])

  const resolveTenantFiles = async (selectedRoot: FileSystemDirectoryHandle) => {
    const yearName = new Date().getFullYear().toString()

    let selectedYear: FileSystemDirectoryHandle | null = null
    try {
      selectedYear = await selectedRoot.getDirectoryHandle(yearName)
    } catch {
      selectedYear = null
    }

    if (!selectedYear) {
      setYearHandle(null)
      setTenantHandle(null)
      setItems([])
      setError('Year folder not found')
      return
    }

    setYearHandle(selectedYear)

    let matchedTenant: FileSystemDirectoryHandle | null = null
    if (tenantBookingId) {
      for await (const [name, handle] of selectedYear.entries()) {
        if (handle.kind === 'directory' && name.startsWith(`${tenantBookingId}_`)) {
          matchedTenant = handle as FileSystemDirectoryHandle
          break
        }
      }
    }

    if (!matchedTenant) {
      setTenantHandle(null)
      setItems([])
      setError('Tenant folder not found')
      return
    }

    setTenantHandle(matchedTenant)

    const nextItems: LocalFolderItem[] = []
    for await (const [name, handle] of matchedTenant.entries()) {
      if (handle.kind === 'directory') {
        nextItems.push({ name, kind: 'directory', handle: handle as FileSystemDirectoryHandle })
        continue
      }
      if (handle.kind === 'file') {
        const fileHandle = handle as FileSystemFileHandle
        const file = await fileHandle.getFile()
        nextItems.push({ name, kind: 'file', size: file.size, handle: fileHandle })
      }
    }

    nextItems.sort((left, right) => {
      if (left.kind !== right.kind) return left.kind === 'directory' ? -1 : 1
      return left.name.localeCompare(right.name)
    })

    setItems(nextItems)
    setError(nextItems.length === 0 ? 'No files in tenant folder' : '')
  }

  useEffect(() => {
    let cancelled = false

    const restoreHandle = async () => {
      const savedHandle = await getDirectoryHandleForUser(userKey)
      if (cancelled || !savedHandle) return

      try {
        const perm = await savedHandle.queryPermission({ mode: 'read' })
        if (cancelled) return

        if (perm === 'granted') {
          setRootHandle(savedHandle)
          setPermissionState('granted')
        } else if (perm === 'prompt') {
          setRootHandle(savedHandle)
          setPermissionState('prompt')
        } else {
          setRootHandle(null)
          setPermissionState('denied')
        }
      } catch {
        if (cancelled) return
        setRootHandle(null)
        setPermissionState('denied')
      }
    }

    setRootHandle(null)
    setYearHandle(null)
    setTenantHandle(null)
    setItems([])
    setPermissionState(null)
    setStagedHandle(null)
    restoreHandle()

    return () => {
      cancelled = true
    }
  }, [userKey])

  useEffect(() => {
    if (!rootHandle || permissionState !== 'granted' || !tenantBookingId) return
    void resolveTenantFiles(rootHandle)
  }, [tenantBookingId, rootHandle, permissionState])

  const handleStageFolder = async () => {
    if (unsupported) {
      setError('Local folder access is not supported in this browser.')
      return
    }

    try {
      const directoryPicker = window as Window & { showDirectoryPicker?: (options?: { mode?: 'read' | 'readwrite' }) => Promise<FileSystemDirectoryHandle> }
      const selectedRoot = await directoryPicker.showDirectoryPicker?.({ mode: 'read' })!
      setStagedHandle(selectedRoot)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setError(err instanceof Error ? err.message : 'Failed to choose folder')
    }
  }

  const handleSave = async () => {
    if (!stagedHandle) return
    await setDirectoryHandleForUser(userKey, stagedHandle)
    setRootHandle(stagedHandle)
    setPermissionState('granted')
    setStagedHandle(null)
    setSettingsOpen(false)
    if (tenantBookingId) {
      await resolveTenantFiles(stagedHandle)
    }
  }

  const handleClear = async () => {
    await clearDirectoryHandleForUser(userKey)
    setRootHandle(null)
    setYearHandle(null)
    setTenantHandle(null)
    setItems([])
    setError('')
    setPermissionState(null)
    setStagedHandle(null)
  }

  const handleReconnect = async () => {
    if (!rootHandle) return
    try {
      const perm = await rootHandle.requestPermission({ mode: 'read' })
      setPermissionState(perm as 'granted' | 'prompt' | 'denied')
      if (perm === 'granted' && tenantBookingId) {
        await resolveTenantFiles(rootHandle)
      }
    } catch {
      setPermissionState('denied')
    }
  }

  const handleOpenFile = async (fileHandle: FileSystemFileHandle) => {
    try {
      const file = await fileHandle.getFile()
      const url = URL.createObjectURL(file)
      window.open(url, '_blank', 'noopener,noreferrer')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to open file')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Files</h2>
          <p className="mt-1 text-sm text-gray-500">
            {!tenantId ? 'No tenant selected' : unsupported ? 'Local folder access is not supported in this browser.' : tenantBookingId ? `Booking ${tenantBookingId}` : 'Loading tenant...'}
          </p>
        </div>
        {!unsupported ? (
          <button
            type="button"
            onClick={() => setSettingsOpen((value) => !value)}
            className="rounded-xl border border-gray-200 bg-white p-2 text-gray-600 transition hover:border-gray-300 hover:bg-gray-50"
            aria-label="Folder settings"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.05.05a2 2 0 0 1-2.83 2.83l-.05-.05A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 1.55V21a2 2 0 0 1-4 0v-.05a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.05.05a2 2 0 0 1-2.83-2.83l.05-.05A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 0 1 0-4h.05a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.05-.05a2 2 0 0 1 2.83-2.83l.05.05A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 0 1 4 0v.05a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.05-.05a2 2 0 0 1 2.83 2.83l-.05.05A1.7 1.7 0 0 0 19.4 9c.58.23.96.79.96 1.4v.2c0 .61-.38 1.17-.96 1.4Z" />
            </svg>
          </button>
        ) : null}
      </div>

      {settingsOpen && !unsupported ? (
        <div className="rounded-2xl border border-gray-200 bg-white p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            {rootHandle ? (
              <p className="text-gray-700">{"\u{1F4C1}"} {rootHandle.name}</p>
            ) : (
              <p className="text-gray-500">No folder selected</p>
            )}
            {rootHandle && permissionState === 'granted' ? <span className="text-emerald-600">Connected</span> : null}
            {rootHandle && permissionState === 'prompt' ? (
              <button type="button" onClick={handleReconnect} className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-700">
                Reconnect
              </button>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={handleStageFolder} className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500">
              Choose folder
            </button>
            {stagedHandle ? (
              <>
                <p className="self-center text-sm text-gray-500">Staged: {stagedHandle.name}</p>
                <button type="button" onClick={handleSave} className="rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-2 text-sm font-semibold text-cyan-700">
                  Save
                </button>
              </>
            ) : null}
            {rootHandle ? (
              <button type="button" onClick={handleClear} className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700">
                Clear
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {loading ? <p className="text-sm text-gray-500">Loading...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {tenantDisplayName ? <p className="text-sm text-gray-500">{tenantDisplayName}</p> : null}
      {rootHandle ? <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Root: {rootHandle.name}</p> : null}
      {yearHandle ? <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Year: {yearHandle.name}</p> : null}
      {tenantHandle ? <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Matched folder: {tenantHandle.name}</p> : null}

      {tenantId ? (
        <ul className="space-y-2">
          {items.length === 0 && !loading && !error ? <li className="text-sm text-gray-500">No files in tenant folder.</li> : null}
          {items.map((item) => (
            <li key={item.name} className="rounded-2xl border border-gray-200 bg-white p-4 transition hover:border-gray-300 hover:bg-gray-50">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-gray-900">{item.name}</p>
                  <p className="mt-1 text-xs uppercase tracking-[0.2em] text-gray-500">
                    {item.kind}
                    {item.size !== undefined ? ` · ${item.size} bytes` : ''}
                  </p>
                </div>
                {item.kind === 'file' ? (
                  <button
                    type="button"
                    onClick={() => handleOpenFile(item.handle as FileSystemFileHandle)}
                    className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs text-cyan-700"
                  >
                    Open
                  </button>
                ) : (
                  <span className="rounded-full border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-600">Folder</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}


