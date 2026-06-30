import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type OneDriveItem = {
  id: string | null
  name: string
  web_url: string | null
  kind: string
  size: number | null
  last_modified: string | null
}

type OneDriveResponse = {
  folder_path: string
  items: OneDriveItem[]
}

type OneDriveBoxProps = {
  tenantId?: number
}

export default function OneDriveBox({ tenantId }: OneDriveBoxProps) {
  const token = useAuthStore((state) => state.token)
  const [items, setItems] = useState<OneDriveItem[]>([])
  const [folderPath, setFolderPath] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!tenantId) {
      setItems([])
      setFolderPath('')
      setError('')
      setLoading(false)
      return
    }

    const controller = new AbortController()
    const loadFiles = async () => {
      try {
        setLoading(true)
        setError('')
        const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/onedrive`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('Failed to load OneDrive files')
        const data: OneDriveResponse = await response.json()
        setItems(data.items)
        setFolderPath(data.folder_path)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load OneDrive files')
      } finally {
        setLoading(false)
      }
    }

    loadFiles()
    return () => controller.abort()
  }, [tenantId, token])

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs uppercase tracking-[0.35em] text-cyan-400">OneDrive</p>
        <h2 className="mt-1 text-xl font-semibold text-white">Tenant folder</h2>
        <p className="mt-1 text-sm text-slate-400">{tenantId ? folderPath || 'Loading folder path...' : 'Select a tenant to view files'}</p>
      </div>

      {loading ? <p className="text-sm text-slate-400">Loading files...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      {tenantId ? (
        <ul className="space-y-2">
          {items.length === 0 && !loading ? <li className="text-sm text-slate-500">No files found.</li> : null}
          {items.map((item) => (
            <li key={item.id ?? item.name} className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4 transition hover:border-slate-700 hover:bg-slate-900">
              <a href={item.web_url ?? '#'} target={item.web_url ? '_blank' : undefined} rel="noreferrer" className="block">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-white">{item.name}</p>
                    <p className="mt-1 text-xs uppercase tracking-[0.2em] text-slate-500">{item.kind}</p>
                  </div>
                  <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-xs text-cyan-300">Open</span>
                </div>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
