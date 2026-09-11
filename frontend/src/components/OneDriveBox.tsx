import { useCallback, useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { getDirectoryHandleForUser } from '../lib/fileHandleStore'
import { useLocalFolderRootPath } from '../lib/displayPreferences'
import { SkeletonText } from './ui/Skeleton'

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

type ServerFolderItem = {
  name: string
  kind: 'file' | 'directory'
  size: number | null
  relative_path: string
}

type OneDriveBoxProps = {
  tenantId?: number
  onReady?: (tenantId: number) => void
}

type FilesTab = 'browser' | 'server'

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`
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
  const [emptyMessage, setEmptyMessage] = useState('')
  const [unsupported, setUnsupported] = useState(false)
  const [activeTab, setActiveTab] = useState<FilesTab>('browser')
  const [serverItems, setServerItems] = useState<ServerFolderItem[]>([])
  const [serverFolderPath, setServerFolderPath] = useState('')
  const [serverLoading, setServerLoading] = useState(false)
  const [serverError, setServerError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)

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
      setEmptyMessage('')
      setLoading(false)
      setServerItems([])
      setServerFolderPath('')
      setServerError('')
      return
    }

    const controller = new AbortController()
    const activeTenantId = tenantId
    const loadTenant = async () => {
      try {
        setLoading(true)
        setError('')
        setEmptyMessage('')
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
    setEmptyMessage('')
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
      setError('')
      setEmptyMessage('Year folder not found.')
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
      setError('')
      setEmptyMessage('Tenant folder not found.')
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
    setError('')
    setEmptyMessage(nextItems.length === 0 ? 'No files in tenant folder.' : '')
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
    setEmptyMessage('')
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

  const loadServerFolder = useCallback(
    async (signal?: AbortSignal) => {
      if (!tenantId) return
      try {
        setServerLoading(true)
        setServerError('')
        const response = await fetch(`${API_BASE_URL}/api/tenant-files/tenant/${tenantId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal,
        })
        if (!response.ok) throw new Error('Failed to load the server folder')
        const data: { folder_path: string; items: ServerFolderItem[] } = await response.json()
        setServerFolderPath(data.folder_path)
        setServerItems(data.items)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setServerError(err instanceof Error ? err.message : 'Failed to load the server folder')
      } finally {
        setServerLoading(false)
      }
    },
    [tenantId, token],
  )

  useEffect(() => {
    if (activeTab !== 'server' || !tenantId) return
    const controller = new AbortController()
    loadServerFolder(controller.signal)
    return () => controller.abort()
  }, [activeTab, tenantId, loadServerFolder])

  const handleUploadFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files)
      if (!tenantId || list.length === 0) return
      setUploading(true)
      setServerError('')
      try {
        for (const file of list) {
          const form = new FormData()
          form.append('file', file)
          const response = await fetch(`${API_BASE_URL}/api/tenant-files/tenant/${tenantId}/upload`, {
            method: 'POST',
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            body: form,
          })
          if (!response.ok) {
            const detail = await response.json().catch(() => null)
            throw new Error(detail?.detail || `Failed to upload ${file.name}`)
          }
        }
        await loadServerFolder()
      } catch (err) {
        setServerError(err instanceof Error ? err.message : 'Upload failed')
      } finally {
        setUploading(false)
      }
    },
    [tenantId, token, loadServerFolder],
  )

  const handleOpenServerFile = async (item: ServerFolderItem) => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/tenant-files/download?path=${encodeURIComponent(item.relative_path)}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
      )
      if (!response.ok) throw new Error('Failed to download file')
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener,noreferrer')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (err) {
      setServerError(err instanceof Error ? err.message : 'Failed to open file')
    }
  }

  const subtitleMessage = !tenantId
    ? 'No tenant selected'
    : activeTab === 'server'
      ? ''
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

      {tenantId ? (
        <div className="flex gap-1 border-b border-gray-200">
          <button
            type="button"
            onClick={() => setActiveTab('browser')}
            className={`px-2.5 py-1 text-xs font-medium ${activeTab === 'browser' ? 'border-b-2 border-brand-500 text-brand-700' : 'text-gray-500 hover:text-gray-700'}`}
          >
            My folder
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('server')}
            className={`px-2.5 py-1 text-xs font-medium ${activeTab === 'server' ? 'border-b-2 border-brand-500 text-brand-700' : 'text-gray-500 hover:text-gray-700'}`}
          >
            Server folder
          </button>
        </div>
      ) : null}

      {activeTab === 'browser' ? (
        <>
          {loading ? <SkeletonText lines={2} className="py-1" /> : null}
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
              {emptyMessage && !loading ? <li className="text-sm text-gray-500">{emptyMessage}</li> : null}
              {items.map((item) => (
                <li key={item.name} className="rounded-xl border border-gray-200 bg-white p-2 transition hover:border-gray-300 hover:bg-gray-50">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="break-words text-sm font-medium text-gray-900">{item.name}</p>
                      <p className="mt-0.5 text-[11px] uppercase tracking-[0.15em] text-gray-500">
                        {item.kind}
                        {item.size !== undefined ? ` - ${formatBytes(item.size)}` : ''}
                      </p>
                    </div>
                    {item.kind === 'file' ? (
                      <button
                        type="button"
                        onClick={() => handleOpenFile(item.handle as FileSystemFileHandle)}
                        className="rounded-full border border-brand-200 bg-brand-50 px-2 py-0.5 text-[11px] text-brand-700"
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
        </>
      ) : null}

      {activeTab === 'server' ? (
        <>
          {serverLoading ? <SkeletonText lines={2} className="py-1" /> : null}
          {serverError ? <p className="text-sm text-rose-400">{serverError}</p> : null}
          {!serverLoading && !serverError && tenantId ? (
            <p className="text-[11px] uppercase tracking-[0.15em] text-gray-500">
              {serverFolderPath ? `Folder: ${serverFolderPath}` : 'No files on the server yet for this booking.'}
            </p>
          ) : null}
          {tenantId ? (
            <label
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                if (e.dataTransfer.files.length) void handleUploadFiles(e.dataTransfer.files)
              }}
              className={`block cursor-pointer rounded-xl border-2 border-dashed p-3 text-center text-xs transition ${
                dragging ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-gray-200 text-gray-500 hover:border-gray-300'
              }`}
            >
              <input
                type="file"
                multiple
                className="hidden"
                disabled={uploading}
                onChange={(e) => {
                  if (e.target.files?.length) void handleUploadFiles(e.target.files)
                  e.target.value = ''
                }}
              />
              {uploading ? 'Uploading…' : 'Drag files here or click to upload to this tenant’s server folder'}
            </label>
          ) : null}
          {tenantId ? (
            <ul className="space-y-1">
              {!serverLoading && !serverError && serverItems.length === 0 ? (
                <li className="text-sm text-gray-500">No files in this tenant's server folder.</li>
              ) : null}
              {serverItems.map((item) => (
                <li key={item.relative_path} className="rounded-xl border border-gray-200 bg-white p-2 transition hover:border-gray-300 hover:bg-gray-50">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="break-words text-sm font-medium text-gray-900">{item.name}</p>
                      <p className="mt-0.5 text-[11px] uppercase tracking-[0.15em] text-gray-500">
                        {item.kind}
                        {item.size != null ? ` - ${formatBytes(item.size)}` : ''}
                      </p>
                    </div>
                    {item.kind === 'file' ? (
                      <button
                        type="button"
                        onClick={() => handleOpenServerFile(item)}
                        className="rounded-full border border-brand-200 bg-brand-50 px-2 py-0.5 text-[11px] text-brand-700"
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
        </>
      ) : null}
    </div>
  )
}
