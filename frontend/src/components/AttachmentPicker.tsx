import { useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import {
  type AttachmentChannel,
  formatBytes,
  maxTotalBytesFor,
  validateAttachmentSelection,
} from '../lib/attachmentLimits'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/api\/?$/, '').replace(/\/$/, '')

export type PendingAttachment = {
  localKey: string
  id: number | null
  filename: string
  size: number
  progress: number
  error?: string
}

export type StoredAttachment = {
  id: number
  filename: string
  mime_type: string | null
  size_bytes: number
  origin: string
  created_at: string
}

type AttachmentPickerProps = {
  tenantId: number
  token: string | null
  channel: AttachmentChannel
  attachments: PendingAttachment[]
  onChange: (next: PendingAttachment[]) => void
  disabled?: boolean
}

let localKeyCounter = 0
const nextLocalKey = () => `local-${Date.now()}-${(localKeyCounter += 1)}`

export default function AttachmentPicker({
  tenantId,
  token,
  channel,
  attachments,
  onChange,
  disabled = false,
}: AttachmentPickerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [history, setHistory] = useState<StoredAttachment[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  // onChange is called from async upload callbacks that close over a stale `attachments`
  // array, so every mutation goes through a ref holding the latest value.
  const attachmentsRef = useRef(attachments)
  useEffect(() => {
    attachmentsRef.current = attachments
  }, [attachments])

  const patchAttachment = useCallback(
    (localKey: string, patch: Partial<PendingAttachment>) => {
      onChange(
        attachmentsRef.current.map((item) => (item.localKey === localKey ? { ...item, ...patch } : item)),
      )
    },
    [onChange],
  )

  const uploadFile = useCallback(
    (file: File, localKey: string) => {
      const formData = new FormData()
      formData.append('files', file)

      // XMLHttpRequest rather than fetch: fetch cannot report upload progress, and a 25MB
      // upload with no feedback looks like a hung UI.
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${API_BASE_URL}/api/communications/tenants/${tenantId}/attachments`)
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      }
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          patchAttachment(localKey, { progress: Math.round((event.loaded / event.total) * 100) })
        }
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const parsed = JSON.parse(xhr.responseText) as StoredAttachment[]
            patchAttachment(localKey, { id: parsed[0]?.id ?? null, progress: 100 })
            return
          } catch {
            patchAttachment(localKey, { error: 'Upload failed', progress: 100 })
            return
          }
        }
        let detail = 'Upload failed'
        try {
          detail = (JSON.parse(xhr.responseText) as { detail?: string }).detail || detail
        } catch {
          // keep the generic message
        }
        patchAttachment(localKey, { error: detail, progress: 100 })
      }
      xhr.onerror = () => patchAttachment(localKey, { error: 'Upload failed', progress: 100 })
      xhr.send(formData)
    },
    [tenantId, token, patchAttachment],
  )

  const addFiles = useCallback(
    (files: File[]) => {
      if (!files.length) return
      const selectedBytes = attachmentsRef.current.reduce((total, item) => total + item.size, 0)
      const errors = validateAttachmentSelection(files, channel, selectedBytes)
      const errorByName = new Map(errors.map((item) => [item.filename, item.reason]))

      const additions: PendingAttachment[] = files.map((file) => ({
        localKey: nextLocalKey(),
        id: null,
        filename: file.name,
        size: file.size,
        progress: 0,
        error: errorByName.get(file.name),
      }))
      onChange([...attachmentsRef.current, ...additions])

      files.forEach((file, index) => {
        const addition = additions[index]
        if (!addition.error) {
          uploadFile(file, addition.localKey)
        }
      })
    },
    [channel, onChange, uploadFile],
  )

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragActive(false)
    if (disabled) return
    addFiles(Array.from(event.dataTransfer.files || []))
  }

  const removeAttachment = (localKey: string) => {
    onChange(attachmentsRef.current.filter((item) => item.localKey !== localKey))
  }

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/attachments`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) {
        setHistory((await response.json()) as StoredAttachment[])
      }
    } finally {
      setHistoryLoading(false)
    }
  }, [tenantId, token])

  const toggleHistory = () => {
    const next = !historyOpen
    setHistoryOpen(next)
    if (next && history.length === 0) {
      void loadHistory()
    }
  }

  const attachFromHistory = (item: StoredAttachment) => {
    if (attachmentsRef.current.some((existing) => existing.id === item.id)) return
    onChange([
      ...attachmentsRef.current,
      {
        localKey: nextLocalKey(),
        id: item.id,
        filename: item.filename,
        size: item.size_bytes,
        progress: 100,
      },
    ])
    setHistoryOpen(false)
  }

  const totalBytes = attachments.reduce((total, item) => total + item.size, 0)
  const totalLimit = maxTotalBytesFor(channel)

  return (
    <div className="space-y-2">
      <div
        onDragOver={(event) => {
          event.preventDefault()
          if (!disabled) setDragActive(true)
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        className={`rounded-lg border border-dashed px-3 py-2 text-xs transition ${
          dragActive ? 'border-cyan-500 bg-cyan-100' : 'border-slate-300 bg-white/60'
        }`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            📎 Attach files
          </button>
          <button
            type="button"
            onClick={toggleHistory}
            disabled={disabled}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            From history
          </button>
          <span className="text-slate-500">
            or drop files here — max {formatBytes(totalLimit)} total
            {totalBytes > 0 ? ` (${formatBytes(totalBytes)} selected)` : ''}
          </span>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(event) => {
            addFiles(Array.from(event.target.files || []))
            event.target.value = ''
          }}
        />

        {historyOpen && (
          <div className="mt-2 max-h-40 overflow-y-auto rounded-md border border-slate-200 bg-white p-1">
            {historyLoading && <p className="px-2 py-1 text-slate-500">Loading…</p>}
            {!historyLoading && history.length === 0 && (
              <p className="px-2 py-1 text-slate-500">No previous attachments for this tenant.</p>
            )}
            {history.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => attachFromHistory(item)}
                className="flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left hover:bg-slate-100"
              >
                <span className="truncate text-slate-700">{item.filename}</span>
                <span className="shrink-0 text-slate-400">{formatBytes(item.size_bytes)}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {attachments.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {attachments.map((item) => (
            <li
              key={item.localKey}
              className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
                item.error ? 'border-rose-300 bg-rose-50 text-rose-700' : 'border-slate-300 bg-white text-slate-700'
              }`}
            >
              <span className="max-w-[16rem] truncate" title={item.error || item.filename}>
                📎 {item.filename}
              </span>
              <span className="text-slate-400">{formatBytes(item.size)}</span>
              {!item.error && item.progress < 100 && (
                <span className="text-cyan-600">{item.progress}%</span>
              )}
              {item.error && <span className="font-medium">{item.error}</span>}
              <button
                type="button"
                onClick={() => removeAttachment(item.localKey)}
                className="text-slate-400 hover:text-slate-700"
                aria-label={`Remove ${item.filename}`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
