import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'

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

type LinkChatModalProps = {
  open: boolean
  threadId: number
  onClose: () => void
  onLinked?: () => void
}

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

export default function LinkChatModal({ open, threadId, onClose, onLinked }: LinkChatModalProps) {
  const token = useAuthStore((state) => state.token)
  const [step, setStep] = useState<'account' | 'chat'>('account')
  const [accounts, setAccounts] = useState<WhatsappAccount[]>([])
  const [accountsLoading, setAccountsLoading] = useState(false)
  const [selectedAccount, setSelectedAccount] = useState<WhatsappAccount | null>(null)
  const [chats, setChats] = useState<WhatsappChat[]>([])
  const [chatsLoading, setChatsLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedChat, setSelectedChat] = useState<WhatsappChat | null>(null)
  const [existingLinks, setExistingLinks] = useState<ThreadWhatsappLink[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined

  useEffect(() => {
    if (!open) return
    setStep('account')
    setSelectedAccount(null)
    setChats([])
    setSearch('')
    setSelectedChat(null)
    setError('')

    const controller = new AbortController()
    const loadAccounts = async () => {
      try {
        setAccountsLoading(true)
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
        if (linksResponse.ok) {
          const linksData: ThreadWhatsappLink[] = await readJsonSafely(linksResponse)
          setExistingLinks(Array.isArray(linksData) ? linksData : [])
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load WhatsApp accounts')
      } finally {
        setAccountsLoading(false)
      }
    }

    loadAccounts()
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, threadId, token])

  useEffect(() => {
    if (!open || step !== 'chat' || !selectedAccount) return

    const controller = new AbortController()
    const loadChats = async () => {
      try {
        setChatsLoading(true)
        setError('')
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
  }, [open, step, selectedAccount, search, token])

  if (!open) return null

  const existingLinkForAccount = selectedAccount
    ? existingLinks.find((link) => link.is_active && link.provider === selectedAccount.provider && link.external_account_id === selectedAccount.external_account_id)
    : null
  const conflictsWithAnotherThread = selectedChat ? selectedChat.already_linked && selectedChat.linked_thread_id !== threadId : false
  const willReplaceExisting = Boolean(existingLinkForAccount && selectedChat && existingLinkForAccount.chat_id !== selectedChat.chat_id)

  const handleSelectAccount = (account: WhatsappAccount) => {
    setSelectedAccount(account)
    setStep('chat')
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
          replace_existing: willReplaceExisting,
        }),
      })
      if (!response.ok) {
        const payload = await readJsonSafely(response)
        throw new Error(getErrorMessage(payload, 'Failed to link WhatsApp chat'))
      }
      onLinked?.()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to link WhatsApp chat')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/45 px-4 backdrop-blur-sm" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="link-chat-modal-title"
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-3xl border border-gray-200 bg-white shadow-sm"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-6 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-emerald-600">WhatsApp</p>
            <h2 id="link-chat-modal-title" className="mt-1 text-2xl font-semibold text-gray-900">
              Link chat
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              {step === 'account' ? 'Choose a WhatsApp service or account.' : `Search the ${selectedAccount?.label} chat list by CHAT_ID or name.`}
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-sm text-gray-500 hover:text-gray-900">
            Close
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {error ? <p className="mb-4 text-sm text-rose-500">{error}</p> : null}

          {step === 'account' ? (
            <div className="space-y-3">
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
              <button type="button" onClick={() => { setStep('account'); setSelectedChat(null) }} className="mb-3 text-xs font-medium text-gray-500 hover:text-gray-900">
                &larr; Back to accounts
              </button>

              <input
                type="text"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search by CHAT_ID or name"
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
                        <span className="truncate font-mono text-sm font-semibold text-gray-900">{chat.chat_id}</span>
                        {isConflict ? (
                          <span className="shrink-0 rounded-full bg-rose-100 px-2 py-1 text-[11px] font-semibold text-rose-700">
                            Linked to thread #{chat.linked_thread_id}
                          </span>
                        ) : chat.already_linked ? (
                          <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-1 text-[11px] font-semibold text-emerald-700">Linked here</span>
                        ) : null}
                      </div>
                      <span className="text-sm text-gray-700">{chat.chat_name || 'No name'}</span>
                      {chat.last_message_preview ? <span className="truncate text-xs text-gray-500">{chat.last_message_preview}</span> : null}
                    </button>
                  )
                })}
              </div>

              {selectedChat ? (
                <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                  <p className="text-xs uppercase tracking-[0.24em] text-emerald-700">Selected chat</p>
                  <p className="mt-1 font-mono text-sm font-semibold text-gray-900">{selectedChat.chat_id}</p>
                  <p className="text-sm text-gray-700">{selectedChat.chat_name || 'No name'}</p>
                  <p className="mt-1 text-xs text-gray-500">Account: {selectedAccount?.label}</p>
                  {conflictsWithAnotherThread ? (
                    <p className="mt-2 text-sm font-semibold text-rose-600">
                      This chat is already linked to thread #{selectedChat.linked_thread_id}. Unlink it there first.
                    </p>
                  ) : willReplaceExisting ? (
                    <p className="mt-2 text-sm font-semibold text-amber-600">
                      This thread already has {existingLinkForAccount?.chat_id} linked for {selectedAccount?.label}. Saving will replace it.
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}
        </div>

        {step === 'chat' ? (
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
              {saving ? 'Linking...' : willReplaceExisting ? 'Replace link' : 'Link chat'}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
