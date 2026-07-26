import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatDisplayDate } from '../lib/date'
import { useDraggablePosition } from '../hooks/useDraggablePosition'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type TenantEmailLink = {
  id: number
  tenant_id: number
  email: string
  beds24_sync_status: string
  source: string
  is_active: boolean
  linked_by_user_id: number | null
  unlinked_at: string | null
  unlinked_by_user_id: number | null
  created_at: string
  updated_at: string
}

type EmailLinkModalProps = {
  open: boolean
  tenantId: number
  tenantName?: string
  bookingId?: string
  onClose: () => void
  onChanged?: () => void
}

type ConflictInfo = {
  message: string
  conflicting_tenant_id: number | null
  conflicting_tenant_name: string | null
}

function getErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = 'detail' in payload ? (payload as { detail?: unknown }).detail : undefined
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string') return message
  }
  return fallback
}

function getConflictInfo(payload: unknown): ConflictInfo | null {
  if (!payload || typeof payload !== 'object') return null
  const detail = 'detail' in payload ? (payload as { detail?: unknown }).detail : undefined
  if (!detail || typeof detail !== 'object') return null
  const record = detail as Record<string, unknown>
  if (typeof record.message !== 'string') return null
  return {
    message: record.message,
    conflicting_tenant_id: typeof record.conflicting_tenant_id === 'number' ? record.conflicting_tenant_id : null,
    conflicting_tenant_name: typeof record.conflicting_tenant_name === 'string' ? record.conflicting_tenant_name : null,
  }
}

async function readJsonSafely(response: Response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function syncStatusLabel(status: string) {
  if (status === 'synced') return { text: 'Synced to Beds24', className: 'text-emerald-700' }
  if (status === 'failed') return { text: 'Beds24 sync failed', className: 'text-rose-600' }
  return { text: 'Syncing to Beds24...', className: 'text-gray-500' }
}

export default function EmailLinkModal({ open, tenantId, tenantName, bookingId, onClose, onChanged }: EmailLinkModalProps) {
  const token = useAuthStore((state) => state.token)
  const [linksLoading, setLinksLoading] = useState(false)
  const [links, setLinks] = useState<TenantEmailLink[]>([])
  const [email, setEmail] = useState('')
  const [conflict, setConflict] = useState<ConflictInfo | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmingUnlinkId, setConfirmingUnlinkId] = useState<number | null>(null)
  const [unlinkingId, setUnlinkingId] = useState<number | null>(null)
  const drag = useDraggablePosition()

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined
  const activeLinks = links.filter((link) => link.is_active)

  useEffect(() => {
    if (!open) return
    setEmail('')
    setConflict(null)
    setError('')
    setConfirmingUnlinkId(null)
    setUnlinkingId(null)

    const controller = new AbortController()
    const loadLinks = async () => {
      try {
        setLinksLoading(true)
        const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/email-links`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (!response.ok) {
          const payload = await readJsonSafely(response)
          throw new Error(getErrorMessage(payload, 'Failed to load linked emails'))
        }
        const data: TenantEmailLink[] = await readJsonSafely(response)
        setLinks(Array.isArray(data) ? data : [])
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load linked emails')
      } finally {
        setLinksLoading(false)
      }
    }

    loadLinks()
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tenantId, token])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  if (!open) return null

  const reloadLinks = async () => {
    const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/email-links`, { headers: authHeaders })
    if (!response.ok) return
    const data: TenantEmailLink[] = await readJsonSafely(response)
    setLinks(Array.isArray(data) ? data : [])
  }

  const submitEmail = async (confirmConflict: boolean) => {
    const trimmed = email.trim()
    if (!trimmed) return
    try {
      setSaving(true)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/email-links`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeaders ?? {}),
        },
        body: JSON.stringify({ email: trimmed, confirm_conflict: confirmConflict }),
      })
      if (response.status === 409 && !confirmConflict) {
        const payload = await readJsonSafely(response)
        const conflictInfo = getConflictInfo(payload)
        if (conflictInfo) {
          setConflict(conflictInfo)
          return
        }
        throw new Error(getErrorMessage(payload, 'This email is already linked elsewhere'))
      }
      if (!response.ok) {
        const payload = await readJsonSafely(response)
        throw new Error(getErrorMessage(payload, 'Failed to link email'))
      }
      setConflict(null)
      setEmail('')
      await reloadLinks()
      onChanged?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to link email')
    } finally {
      setSaving(false)
    }
  }

  const handleUnlink = async (link: TenantEmailLink) => {
    if (unlinkingId) return
    try {
      setUnlinkingId(link.id)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/email-links/${link.id}`, {
        method: 'DELETE',
        headers: authHeaders,
      })
      if (!response.ok) {
        const payload = await readJsonSafely(response)
        throw new Error(getErrorMessage(payload, 'Failed to unlink email'))
      }
      setConfirmingUnlinkId(null)
      await reloadLinks()
      onChanged?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to unlink email')
    } finally {
      setUnlinkingId(null)
    }
  }

  const tenantSubtitle = [tenantName ? `Tenant: ${tenantName}` : null, bookingId ? `Booking #${bookingId}` : null].filter(Boolean).join(' · ')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="link-email-modal-title"
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-3xl border border-gray-200 bg-white shadow-sm"
        style={drag.style}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          className="flex cursor-move items-start justify-between gap-4 border-b border-gray-200 px-6 py-4"
          onPointerDown={drag.handlePointerDown}
        >
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-emerald-600">Email</p>
            <h2 id="link-email-modal-title" className="mt-1 text-2xl font-semibold text-gray-900">
              Manage linked emails
            </h2>
            {tenantSubtitle ? <p className="mt-1 text-sm text-gray-500">{tenantSubtitle}</p> : null}
            <p className="mt-1 text-sm text-gray-500">
              Linked emails are matched to incoming Gmail messages and pushed to Beds24 as a booking info item.
            </p>
          </div>
          <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={onClose} className="text-sm text-gray-500 hover:text-gray-900">
            Close
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {error ? <p className="mb-4 text-sm text-rose-500">{error}</p> : null}

          <div className="space-y-3">
            {linksLoading ? <p className="text-sm text-gray-500">Loading linked emails...</p> : null}
            {!linksLoading && activeLinks.length === 0 ? (
              <p className="text-sm text-gray-500">No emails are linked to this tenant yet.</p>
            ) : null}
            {activeLinks.map((link) => {
              const statusLabel = syncStatusLabel(link.beds24_sync_status)
              return (
                <div key={link.id} className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                  <p className="truncate text-sm font-semibold text-gray-900">{link.email}</p>
                  <p className="mt-1 text-xs text-gray-500">
                    Linked {formatDisplayDate(link.created_at)}
                    {link.linked_by_user_id ? ` by user #${link.linked_by_user_id}` : ''}
                  </p>
                  <p className={`mt-1 text-xs ${statusLabel.className}`}>{statusLabel.text}</p>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {confirmingUnlinkId === link.id ? (
                      <span className="flex items-center gap-2 rounded-lg border border-rose-200 bg-white px-2 py-1 text-xs">
                        <span className="font-medium text-rose-700">Unlink this email?</span>
                        <button
                          type="button"
                          disabled={unlinkingId === link.id}
                          onClick={() => handleUnlink(link)}
                          className="font-semibold text-rose-600 hover:text-rose-800 disabled:opacity-50"
                        >
                          {unlinkingId === link.id ? 'Unlinking...' : 'Confirm'}
                        </button>
                        <button type="button" onClick={() => setConfirmingUnlinkId(null)} className="text-gray-500 hover:text-gray-900">
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmingUnlinkId(link.id)}
                        className="rounded-lg border border-rose-200 bg-white px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50"
                      >
                        Unlink
                      </button>
                    )}
                  </div>
                </div>
              )
            })}

            <div className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.24em] text-gray-500">Add email</p>
              <div className="mt-2 flex gap-2">
                <input
                  type="email"
                  value={email}
                  onChange={(event) => {
                    setEmail(event.target.value)
                    setConflict(null)
                  }}
                  placeholder="guest@example.com"
                  className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <button
                  type="button"
                  disabled={!email.trim() || saving}
                  onClick={() => submitEmail(false)}
                  className="shrink-0 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500"
                >
                  {saving ? 'Linking...' : 'Link'}
                </button>
              </div>

              {conflict ? (
                <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
                  <p className="text-sm font-semibold text-amber-700">
                    {conflict.message}
                    {conflict.conflicting_tenant_name ? ` (${conflict.conflicting_tenant_name})` : ''}
                  </p>
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => submitEmail(true)}
                      className="rounded-lg bg-amber-600 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-50"
                    >
                      Link anyway
                    </button>
                    <button type="button" onClick={() => setConflict(null)} className="text-xs text-gray-500 hover:text-gray-900">
                      Cancel
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
