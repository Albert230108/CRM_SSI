import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatDisplayDate } from '../lib/date'
import { useDraggablePosition } from '../hooks/useDraggablePosition'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type WhatsappAccount = {
  external_account_id: string
  provider: string
  label: string
}

type WhatsappChat = {
  chat_id: string
  chat_name: string | null
  provider: string
  external_account_id: string
  last_message_timestamp: string | null
  last_message_preview: string | null
  already_linked: boolean
  linked_thread_id: number | null
}

type ThreadWhatsappLink = {
  id: number
  thread_id: number
  provider: string
  external_account_id: string
  chat_id: string
  chat_display_name: string | null
  is_active: boolean
  linked_by_user_id: number | null
  unlinked_at: string | null
  unlinked_by_user_id: number | null
  created_at: string
  updated_at: string
}

type ResyncResult = {
  state: 'success' | 'error'
  message: string
}

type LinkChatModalProps = {
  open: boolean
  threadId: number
  tenantName?: string
  bookingId?: string
  onClose: () => void
  onChanged?: () => void
}

type View = 'linked' | 'account' | 'chat'

function getErrorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== 'object') return fallback
  const detail = 'detail' in payload ? (payload as { detail?: unknown }).detail : undefined
  if (typeof detail === 'string') return detail
  return fallback
}

async function readJsonSafely(response: Response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

// Names saved before the @lid display-name fix may still hold the raw WhatsApp id
// (e.g. "37284873@lid") instead of a real name — don't surface that opaque id as a name.
const RAW_WHATSAPP_ID_PATTERN = /^\d+@(lid|c\.us|g\.us|s\.whatsapp\.net)$/i

function formatChatDisplayName(name: string | null | undefined) {
  if (!name || RAW_WHATSAPP_ID_PATTERN.test(name.trim())) {
    return 'Unknown contact'
  }
  return name
}

export default function LinkChatModal({ open, threadId, tenantName, bookingId, onClose, onChanged }: LinkChatModalProps) {
  const token = useAuthStore((state) => state.token)
  const [view, setView] = useState<View>('account')
  const [linksLoading, setLinksLoading] = useState(false)
  const [existingLinks, setExistingLinks] = useState<ThreadWhatsappLink[]>([])
  const [accounts, setAccounts] = useState<WhatsappAccount[]>([])
  const [accountsLoading, setAccountsLoading] = useState(false)
  const [selectedAccount, setSelectedAccount] = useState<WhatsappAccount | null>(null)
  const [chats, setChats] = useState<WhatsappChat[]>([])
  const [chatsLoading, setChatsLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedChat, setSelectedChat] = useState<WhatsappChat | null>(null)
  const [replaceTarget, setReplaceTarget] = useState<ThreadWhatsappLink | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmingUnlinkId, setConfirmingUnlinkId] = useState<number | null>(null)
  const [unlinkingId, setUnlinkingId] = useState<number | null>(null)
  const [resyncingId, setResyncingId] = useState<number | null>(null)
  const [resyncResults, setResyncResults] = useState<Record<number, ResyncResult>>({})
  const drag = useDraggablePosition()

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined
  const activeLinks = existingLinks.filter((link) => link.is_active)

  useEffect(() => {
    if (!open) return
    setSelectedAccount(null)
    setChats([])
    setSearch('')
    setSelectedChat(null)
    setReplaceTarget(null)
    setError('')
    setConfirmingUnlinkId(null)
    setUnlinkingId(null)
    setResyncingId(null)
    setResyncResults({})

    const controller = new AbortController()
    const loadInitial = async () => {
      try {
        setAccountsLoading(true)
        setLinksLoading(true)
        const [accountsResponse, linksResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/whatsapp/accounts`, { headers: authHeaders, signal: controller.signal }),
          fetch(`${API_BASE_URL}/api/threads/${threadId}/whatsapp-links`, { headers: authHeaders, signal: controller.signal }),
        ])
        if (!accountsResponse.ok) {
          const payload = await readJsonSafely(accountsResponse)
          throw new Error(getErrorMessage(payload, 'Failed to load WhatsApp accounts'))
        }
        const accountsData: WhatsappAccount[] = await readJsonSafely(accountsResponse)
        setAccounts(Array.isArray(accountsData) ? accountsData : [])
        let links: ThreadWhatsappLink[] = []
        if (linksResponse.ok) {
          const linksData: ThreadWhatsappLink[] = await readJsonSafely(linksResponse)
          links = Array.isArray(linksData) ? linksData : []
        }
        setExistingLinks(links)
        setView(links.some((link) => link.is_active) ? 'linked' : 'account')
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load WhatsApp accounts')
      } finally {
        setAccountsLoading(false)
        setLinksLoading(false)
      }
    }

    loadInitial()
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, threadId, token])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  useEffect(() => {
    if (!open || view !== 'chat' || !selectedAccount) return

    const controller = new AbortController()
    const loadChats = async () => {
      try {
        setChatsLoading(true)
        setError('')
        setChats([])
        const params = new URLSearchParams({ provider: selectedAccount.provider })
        if (search.trim()) params.set('search', search.trim())
        const response = await fetch(
          `${API_BASE_URL}/api/whatsapp/accounts/${encodeURIComponent(selectedAccount.external_account_id)}/chats?${params.toString()}`,
          { headers: authHeaders, signal: controller.signal },
        )
        if (!response.ok) {
          const payload = await readJsonSafely(response)
          throw new Error(getErrorMessage(payload, 'Failed to load WhatsApp chat list'))
        }
        const data: WhatsappChat[] = await readJsonSafely(response)
        setChats(Array.isArray(data) ? data : [])
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load WhatsApp chat list')
      } finally {
        setChatsLoading(false)
      }
    }

    const debounce = setTimeout(loadChats, 250)
    return () => {
      clearTimeout(debounce)
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, view, selectedAccount, search, token])

  if (!open) return null

  const reloadLinks = async () => {
    const response = await fetch(`${API_BASE_URL}/api/threads/${threadId}/whatsapp-links`, { headers: authHeaders })
    if (!response.ok) return
    const data: ThreadWhatsappLink[] = await readJsonSafely(response)
    setExistingLinks(Array.isArray(data) ? data : [])
  }

  const conflictsWithAnotherThread = selectedChat ? selectedChat.already_linked && selectedChat.linked_thread_id !== threadId : false
  // A tenant can have several active chats linked on the same account at once, so picking a new
  // chat only replaces an existing link when the user explicitly chose "Replace" on that specific
  // link (replaceTarget) -- otherwise it's simply added alongside whatever is already linked.
  const willReplaceExisting = Boolean(replaceTarget && selectedChat && replaceTarget.chat_id !== selectedChat.chat_id)

  const handleSelectAccount = (account: WhatsappAccount, replaceTargetLink: ThreadWhatsappLink | null = null) => {
    setSelectedAccount(account)
    setSelectedChat(null)
    setReplaceTarget(replaceTargetLink)
    setView('chat')
  }

  const handleSave = async () => {
    if (!selectedAccount || !selectedChat || conflictsWithAnotherThread) return
    try {
      setSaving(true)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/threads/${threadId}/whatsapp-links`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authHeaders ?? {}),
        },
        body: JSON.stringify({
          provider: selectedAccount.provider,
          external_account_id: selectedAccount.external_account_id,
          chat_id: selectedChat.chat_id,
          chat_display_name: selectedChat.chat_name,
          replace_link_id: replaceTarget?.id ?? null,
        }),
      })
      if (!response.ok) {
        const payload = await readJsonSafely(response)
        throw new Error(getErrorMessage(payload, 'Failed to link WhatsApp chat'))
      }
      await reloadLinks()
      setSelectedChat(null)
      setSelectedAccount(null)
      setReplaceTarget(null)
      setView('linked')
      onChanged?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to link WhatsApp chat')
    } finally {
      setSaving(false)
    }
  }

  const handleUnlink = async (link: ThreadWhatsappLink) => {
    if (unlinkingId) return
    try {
      setUnlinkingId(link.id)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/threads/${threadId}/whatsapp-links/${link.id}`, {
        method: 'DELETE',
        headers: authHeaders,
      })
      if (!response.ok) {
        const payload = await readJsonSafely(response)
        throw new Error(getErrorMessage(payload, 'Failed to unlink WhatsApp chat'))
      }
      setConfirmingUnlinkId(null)
      await reloadLinks()
      onChanged?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to unlink WhatsApp chat')
    } finally {
      setUnlinkingId(null)
    }
  }

  const handleResync = async (link: ThreadWhatsappLink) => {
    if (resyncingId) return
    try {
      setResyncingId(link.id)
      setError('')
      setResyncResults((current) => {
        const next = { ...current }
        delete next[link.id]
        return next
      })
      const response = await fetch(`${API_BASE_URL}/api/threads/${threadId}/whatsapp-links/${link.id}/resync`, {
        method: 'POST',
        headers: authHeaders,
      })
      const payload = await readJsonSafely(response)
      if (!response.ok) {
        throw new Error(getErrorMessage(payload, 'Failed to resync WhatsApp chat history'))
      }
      const resync = payload?.resync as
        | { ok: boolean; fetched: number; imported: number; deduped: number; skipped_no_content: number; error?: string | null }
        | undefined
      if (!resync?.ok) {
        throw new Error(resync?.error || 'Failed to resync WhatsApp chat history')
      }
      const skippedSuffix = resync.skipped_no_content > 0 ? `, ${resync.skipped_no_content} had no content (call logs/system events)` : ''
      setResyncResults((current) => ({
        ...current,
        [link.id]: { state: 'success', message: `Done: ${resync.fetched} fetched, ${resync.imported} imported, ${resync.deduped} already synced${skippedSuffix}` },
      }))
      await reloadLinks()
      onChanged?.()
    } catch (err) {
      setResyncResults((current) => ({
        ...current,
        [link.id]: { state: 'error', message: err instanceof Error ? err.message : 'Failed to resync WhatsApp chat history' },
      }))
    } finally {
      setResyncingId(null)
    }
  }

  const tenantSubtitle = [tenantName ? `Tenant: ${tenantName}` : null, bookingId ? `Booking #${bookingId}` : null].filter(Boolean).join(' · ')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="link-chat-modal-title"
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-3xl border border-gray-200 bg-white shadow-sm"
        style={drag.style}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          className="flex cursor-move items-start justify-between gap-4 border-b border-gray-200 px-6 py-4"
          onPointerDown={drag.handlePointerDown}
        >
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-emerald-600">WhatsApp</p>
            <h2 id="link-chat-modal-title" className="mt-1 text-2xl font-semibold text-gray-900">
              {view === 'linked' ? 'Manage linked chats' : 'Link chat'}
            </h2>
            {tenantSubtitle ? <p className="mt-1 text-sm text-gray-500">{tenantSubtitle}</p> : null}
            <p className="mt-1 text-sm text-gray-500">
              {view === 'linked'
                ? 'Manage this tenant\'s linked WhatsApp chats.'
                : view === 'account'
                  ? 'Choose a WhatsApp service or account.'
                  : `Search the ${selectedAccount?.label} chat list by phone number, name, or message text.`}
            </p>
          </div>
          <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={onClose} className="text-sm text-gray-500 hover:text-gray-900">
            Close
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {error ? <p className="mb-4 text-sm text-rose-500">{error}</p> : null}

          {view === 'linked' ? (
            <div className="space-y-3">
              {linksLoading ? <p className="text-sm text-gray-500">Loading linked chats...</p> : null}
              {!linksLoading && activeLinks.length === 0 ? (
                <p className="text-sm text-gray-500">No WhatsApp chats are linked to this tenant yet.</p>
              ) : null}
              {activeLinks.map((link) => (
                <div key={link.id} className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                  <p className="text-[11px] uppercase tracking-[0.24em] text-emerald-700">
                    {link.provider} · {link.external_account_id}
                  </p>
                  <p className="mt-1 truncate text-sm font-semibold text-gray-900">{formatChatDisplayName(link.chat_display_name)}</p>
                  <p className="truncate font-mono text-[11px] text-gray-400">{link.chat_id}</p>
                  <p className="mt-1 text-xs text-gray-500">
                    Linked {formatDisplayDate(link.created_at)}
                    {link.linked_by_user_id ? ` by user #${link.linked_by_user_id}` : ''}
                  </p>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      disabled={resyncingId === link.id}
                      onClick={() => handleResync(link)}
                      title="Pull the chat's entire history again (fixes chats that were only partially synced)"
                      className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50"
                    >
                      {resyncingId === link.id ? 'Resyncing...' : 'Resync full history'}
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() =>
                        handleSelectAccount(
                          accounts.find((account) => account.provider === link.provider && account.external_account_id === link.external_account_id) ?? {
                            provider: link.provider,
                            external_account_id: link.external_account_id,
                            label: link.external_account_id,
                          },
                          link,
                        )
                      }
                      className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:text-gray-900"
                    >
                      Replace
                    </button>
                    {confirmingUnlinkId === link.id ? (
                      <span className="flex items-center gap-2 rounded-lg border border-rose-200 bg-white px-2 py-1 text-xs">
                        <span className="font-medium text-rose-700">Unlink this chat?</span>
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
                  {resyncResults[link.id] ? (
                    <p className={`mt-2 text-xs ${resyncResults[link.id].state === 'error' ? 'text-rose-600' : 'text-emerald-700'}`}>
                      {resyncResults[link.id].message}
                    </p>
                  ) : null}
                </div>
              ))}

              <button
                type="button"
                onClick={() => {
                  setSelectedAccount(null)
                  setReplaceTarget(null)
                  setView('account')
                }}
                className="w-full rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700 hover:bg-emerald-100"
              >
                Link another chat
              </button>
            </div>
          ) : view === 'account' ? (
            <div className="space-y-3">
              {activeLinks.length > 0 ? (
                <button type="button" onClick={() => setView('linked')} className="mb-1 text-xs font-medium text-gray-500 hover:text-gray-900">
                  &larr; Back to linked chats
                </button>
              ) : null}
              {accountsLoading ? <p className="text-sm text-gray-500">Loading WhatsApp accounts...</p> : null}
              {!accountsLoading && accounts.length === 0 ? (
                <p className="text-sm text-gray-500">No WhatsApp accounts are configured for linking.</p>
              ) : null}
              {accounts.map((account) => (
                <button
                  key={account.external_account_id}
                  type="button"
                  onClick={() => handleSelectAccount(account)}
                  className="flex w-full items-center justify-between rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-left transition hover:border-emerald-300 hover:bg-emerald-50"
                >
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{account.label}</p>
                    <p className="mt-1 font-mono text-xs text-gray-500">{account.external_account_id}</p>
                  </div>
                  <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-gray-600 shadow-sm">Select</span>
                </button>
              ))}
            </div>
          ) : (
            <div>
              <button
                type="button"
                onClick={() => {
                  setView('account')
                  setSelectedChat(null)
                  setReplaceTarget(null)
                }}
                className="mb-3 text-xs font-medium text-gray-500 hover:text-gray-900"
              >
                &larr; Back to accounts
              </button>

              <input
                type="text"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search by phone number, name, or message text"
                className="mb-4 w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />

              {chatsLoading ? <p className="text-sm text-gray-500">Loading chats...</p> : null}
              {!chatsLoading && chats.length === 0 ? <p className="text-sm text-gray-500">No matching chats found.</p> : null}

              <div className="space-y-2">
                {chats.map((chat) => {
                  const isSelected = selectedChat?.chat_id === chat.chat_id
                  const isConflict = chat.already_linked && chat.linked_thread_id !== threadId
                  return (
                    <button
                      key={chat.chat_id}
                      type="button"
                      onClick={() => setSelectedChat(chat)}
                      className={`flex w-full flex-col gap-1 rounded-2xl border px-4 py-3 text-left transition ${
                        isSelected ? 'border-emerald-400 bg-emerald-50' : 'border-gray-200 bg-gray-50 hover:border-emerald-200'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-gray-900">{formatChatDisplayName(chat.chat_name)}</span>
                        {isConflict ? (
                          <span className="shrink-0 rounded-full bg-rose-100 px-2 py-1 text-[11px] font-semibold text-rose-700">
                            Linked to thread #{chat.linked_thread_id}
                          </span>
                        ) : chat.already_linked ? (
                          <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-1 text-[11px] font-semibold text-emerald-700">Linked here</span>
                        ) : null}
                      </div>
                      <span className="truncate font-mono text-[11px] text-gray-400">{chat.chat_id}</span>
                      {chat.last_message_preview ? <span className="truncate text-xs text-gray-500">{chat.last_message_preview}</span> : null}
                    </button>
                  )
                })}
              </div>

              {selectedChat ? (
                <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.24em] text-emerald-700">Confirm link</p>
                  {tenantSubtitle ? <p className="mt-1 text-xs text-gray-500">{tenantSubtitle}</p> : null}
                  <p className="mt-1 text-xs text-gray-500">Account: {selectedAccount?.label}</p>
                  <p className="mt-1 text-sm font-semibold text-gray-900">{formatChatDisplayName(selectedChat.chat_name)}</p>
                  <p className="font-mono text-[11px] text-gray-400">{selectedChat.chat_id}</p>
                  {conflictsWithAnotherThread ? (
                    <p className="mt-2 text-sm font-semibold text-rose-600">
                      This chat is already linked to thread #{selectedChat.linked_thread_id}. Unlink it there first.
                    </p>
                  ) : willReplaceExisting ? (
                    <p className="mt-2 text-sm font-semibold text-amber-600">
                      Confirming will replace {formatChatDisplayName(replaceTarget?.chat_display_name)} ({replaceTarget?.chat_id}) with this chat.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}
        </div>

        {view === 'chat' ? (
          <div className="flex justify-end gap-3 border-t border-gray-200 px-6 py-4">
            <button type="button" onClick={onClose} className="rounded-xl px-4 py-2 text-sm text-gray-500 hover:text-gray-900">
              Cancel
            </button>
            <button
              type="button"
              disabled={!selectedChat || conflictsWithAnotherThread || saving}
              onClick={handleSave}
              className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500"
            >
              {saving ? 'Linking...' : 'Confirm link'}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
