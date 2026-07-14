import { useEffect, useMemo, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { getDirectoryHandleForUser } from '../lib/fileHandleStore'

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
  const userEmail = useAuthStore((state) => state.user?.email)
  const userKey = userEmail ?? 'anonymous'
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
            {!tenantId ? 'No tenant selected' : unsupported ? 'Local folder access is not supported in this browser.' : !rootHandle ? 'No folder configured - go to Settings to connect a local folder.' : tenantBookingId ? 'Local booking files' : 'Loading tenant...'}
          </p>
        </div>
      </div>

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
                    {item.size !== undefined ? ` - ${item.size} bytes` : ''}
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

