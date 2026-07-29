import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { getDirectoryHandleForUser } from '../lib/fileHandleStore'
import { useLocalFolderRootPath } from '../lib/displayPreferences'

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
  onReady?: (tenantId: number) => void
}

export default function OneDriveBox({ tenantId, onReady }: OneDriveBoxProps) {
  const token = useAuthStore((state) => state.token)
  const userEmail = useAuthStore((state) => state.user?.email)
  const userKey = userEmail ?? 'anonymous'
  const [localFolderRootPath] = useLocalFolderRootPath()
  const [copiedPath, setCopiedPath] = useState(false)
  const [tenant, setTenant] = useState<TenantSummary | null>(null)
  const [rootHandle, setRootHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [yearHandle, setYearHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [tenantHandle, setTenantHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [items, setItems] = useState<LocalFolderItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [unsupported, setUnsupported] = useState(false)

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
    const activeTenantId = tenantId
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
        onReady?.(activeTenantId)
      }
    }

    loadTenant()
    return () => controller.abort()
  }, [tenantId, token])

  const tenantBookingId = tenant?.booking_id?.trim() || ''

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
        }
      } catch {
        return
      }
    }

    setRootHandle(null)
    setYearHandle(null)
    setTenantHandle(null)
    setItems([])
    setError('')
    restoreHandle()

    return () => {
      cancelled = true
    }
  }, [userKey])

  useEffect(() => {
    if (rootHandle && tenantBookingId) {
      void resolveTenantFiles(rootHandle)
    }
  }, [rootHandle, tenantBookingId])

  const handleCopyExplorerPath = async () => {
    if (!localFolderRootPath || !yearHandle || !tenantHandle) return
    const trimmedRoot = localFolderRootPath.replace(/[\\/]+$/, '')
    const fullPath = `${trimmedRoot}\\${yearHandle.name}\\${tenantHandle.name}`
    try {
      await navigator.clipboard.writeText(fullPath)
      setCopiedPath(true)
      window.setTimeout(() => setCopiedPath(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to copy folder path')
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

  const subtitleMessage = !tenantId
    ? 'No tenant selected'
    : unsupported
      ? 'Local folder access is not supported in this browser.'
      : !rootHandle
        ? 'No folder configured - go to Settings to connect a local folder.'
        : tenantBookingId
          ? ''
          : 'Loading tenant...'

  return (
    <div className="min-w-0 space-y-1.5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Files</h2>
          {subtitleMessage ? <p className="mt-1 text-sm text-gray-500">{subtitleMessage}</p> : null}
        </div>
        {tenantHandle ? (
          <button
            type="button"
            onClick={handleCopyExplorerPath}
            disabled={!localFolderRootPath}
            title={!localFolderRootPath ? 'Set a root folder path in Settings to enable this' : 'Copy this tenant\'s folder path to open in File Explorer'}
            className="shrink-0 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-700 transition hover:border-gray-300 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {copiedPath ? 'Path copied!' : 'Copy Explorer path'}
          </button>
        ) : null}
      </div>

      {loading ? <p className="text-sm text-gray-500">Loading...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {rootHandle ? (
        <p className="text-[11px] uppercase tracking-[0.15em] text-gray-500">
          {[
            `Root: ${rootHandle.name}`,
            yearHandle ? `Year: ${yearHandle.name}` : null,
            tenantHandle ? `Folder: ${tenantHandle.name}` : null,
          ]
            .filter(Boolean)
            .join(' | ')}
        </p>
      ) : null}

      {tenantId ? (
        <ul className="space-y-1">
          {items.length === 0 && !loading && !error ? <li className="text-sm text-gray-500">No files in tenant folder.</li> : null}
          {items.map((item) => (
            <li key={item.name} className="rounded-xl border border-gray-200 bg-white p-2 transition hover:border-gray-300 hover:bg-gray-50">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="break-words text-sm font-medium text-gray-900">{item.name}</p>
                  <p className="mt-0.5 text-[11px] uppercase tracking-[0.15em] text-gray-500">
                    {item.kind}
                    {item.size !== undefined ? ` - ${item.size} bytes` : ''}
                  </p>
                </div>
                {item.kind === 'file' ? (
                  <button
                    type="button"
                    onClick={() => handleOpenFile(item.handle as FileSystemFileHandle)}
                    className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-[11px] text-cyan-700"
                  >
                    Open
                  </button>
                ) : (
                  <span className="rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[11px] text-gray-600">Folder</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

