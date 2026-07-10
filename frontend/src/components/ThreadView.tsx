import { useEffect, useState, type FormEvent } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatDisplayDate } from '../lib/date'
import LinkChatModal from './LinkChatModal'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/api\/?$/, '').replace(/\/$/, '')

const BLOCK_TAGS = new Set(['ADDRESS', 'ARTICLE', 'BLOCKQUOTE', 'DIV', 'DL', 'DT', 'DD', 'FIELDSET', 'FIGCAPTION', 'FIGURE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'LI', 'OL', 'P', 'PRE', 'SECTION', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'UL'])
const ALLOWED_TAGS = new Set(['A', 'B', 'BR', 'CODE', 'DIV', 'EM', 'I', 'LI', 'OL', 'P', 'PRE', 'SPAN', 'STRONG', 'SUB', 'SUP', 'U', 'UL', 'BLOCKQUOTE'])
const ALLOWED_ATTRS = new Set(['href', 'title', 'target', 'rel'])
type TimelineMessage = {
  id: number
  provider: string
  provider_message_id: string
  direction: 'inbound' | 'outbound' | string
  sender_email: string | null
  recipient_email: string | null
  subject: string | null
  body: string
  body_text: string | null
  body_html: string | null
  external_account_id?: string | null
  external_phone_id?: string | null
  whatsapp_chat_id?: string | null
  sent_at: string
}

const decodeHtmlEntities = (value: string) => {
  const textarea = document.createElement('textarea')
  textarea.innerHTML = value
  return textarea.value
}

const htmlToPlainText = (html: string) => {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const chunks: string[] = []
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent || ''
      if (text.trim()) chunks.push(text)
      return
    }
    if (!(node instanceof HTMLElement)) return
    const tag = node.tagName
    if (tag === 'BR') {
      chunks.push('\n')
      return
    }
    const isBlock = BLOCK_TAGS.has(tag)
    if (isBlock && chunks.length && !chunks[chunks.length - 1]?.endsWith('\n')) chunks.push('\n')
    node.childNodes.forEach(walk)
    if (isBlock && !chunks[chunks.length - 1]?.endsWith('\n')) chunks.push('\n')
  }
  doc.body.childNodes.forEach(walk)
  return decodeHtmlEntities(chunks.join(' ').replace(/\s+\n/g, '\n').replace(/\n\s+/g, '\n').replace(/[ \t]{2,}/g, ' ').trim())
}

const sanitizeHtml = (html: string) => {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) return
    if (!(node instanceof HTMLElement)) return
    if (!ALLOWED_TAGS.has(node.tagName)) {
      const parent = node.parentNode
      if (!parent) return
      while (node.firstChild) parent.insertBefore(node.firstChild, node)
      parent.removeChild(node)
      return
    }
    Array.from(node.attributes).forEach((attr) => {
      if (!ALLOWED_ATTRS.has(attr.name.toLowerCase())) {
        node.removeAttribute(attr.name)
        return
      }
      if (attr.name.toLowerCase() === 'href') {
        const value = attr.value.trim()
        if (!/^https?:|^mailto:|^tel:/i.test(value)) {
          node.removeAttribute(attr.name)
          return
        }
        node.setAttribute('target', '_blank')
        node.setAttribute('rel', 'noreferrer noopener')
      }
    })
    Array.from(node.childNodes).forEach(walk)
  }
  Array.from(doc.body.childNodes).forEach(walk)
  return doc.body.innerHTML
}

const extractPreviewText = (message: Pick<TimelineMessage, 'body' | 'body_text' | 'body_html'>) => {
  const source = message.body_text || message.body_html || message.body || ''
  if (!source) return ''
  if (message.body_html || /<[^>]+>/.test(source)) {
    return htmlToPlainText(source).replace(/\s+/g, ' ').trim()
  }
  return source.replace(/\s+/g, ' ').trim()
}

const extractWhatsappPreviewText = (message: { message: string }) => message.message.replace(/\s+/g, ' ').trim()

const renderMessageBody = (message: Pick<TimelineMessage, 'body' | 'body_text' | 'body_html'>) => {
  const html = message.body_html || ''
  if (html) {
    return { __html: sanitizeHtml(html) }
  }
  return undefined
}
type EmailThreadItem = {
  type: 'email_thread'
  id: number
  provider_account_id: number | null
  provider_account_email: string | null
  provider_account_display_name: string | null
  thread_id: number
  provider_thread_id: string
  subject: string | null
  preview_text: string | null
  anchor_timestamp: string
  messages: TimelineMessage[]
  whatsapp_blocks: {
    block_id: string
    start_at: string | null
    end_at: string | null
    messages: TimelineMessage[]
    message_count: number
  }[]
}

type WhatsappGroupItem = {
  type: 'whatsapp_group'
  group_id: string
  start_timestamp: string | null
  end_timestamp: string | null
  messages: WhatsappTimelineMessage[]
  message_count: number
}

type ThreadItem = EmailThreadItem | WhatsappGroupItem

type GroupedThreadResponse = {
  tenant_id: number
  tenant_name: string
  items: ThreadItem[]
}

type TenantSummary = {
  id: number
  name: string
  email: string | null
  phone: string | null
}

type WhatsappEndpointOption = {
  id: number
  tenant_id: number
  channel_type: string
  provider: string
  external_account_id: string | null
  external_phone_id: string | null
  external_chat_namespace: string | null
  routing_strategy: string
  is_active: boolean
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

const formatWhatsappEndpointLabel = (endpoint: WhatsappEndpointOption) => {
  const parts = [endpoint.external_account_id || `Endpoint ${endpoint.id}`]
  if (endpoint.external_phone_id) parts.push(endpoint.external_phone_id)
  if (endpoint.provider) parts.push(endpoint.provider)
  if (endpoint.routing_strategy) parts.push(endpoint.routing_strategy)
  return parts.join(' - ')
}

type WhatsappTimelineMessage = {
  id: number
  tenant_id: number
  channel: string
  direction: 'inbound' | 'outbound' | string
  provider: string | null
  external_account_id: string | null
  external_phone_id: string | null
  external_chat_namespace: string | null
  whatsapp_chat_id: string | null
  provider_message_id: string | null
  subject: string | null
  message: string
  created_at: string
}

type ThreadViewProps = {
  tenantId?: number
  reloadSignal?: number
}

type ReplyTarget =
  | { type: 'email'; threadId: number; providerThreadId: string; providerAccountId: number; subject: string | null }
  | { type: 'whatsapp'; groupId: string }
  | null

export default function ThreadView({ tenantId, reloadSignal }: ThreadViewProps) {
  const token = useAuthStore((state) => state.token)
  const [tenant, setTenant] = useState<TenantSummary | null>(null)
  const [items, setItems] = useState<ThreadItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expandedConversationIds, setExpandedConversationIds] = useState<number[]>([])
  const [expandedWhatsappBlockIds, setExpandedWhatsappBlockIds] = useState<string[]>([])
  const [selectedWhatsappGroup, setSelectedWhatsappGroup] = useState<WhatsappGroupItem | null>(null)
  const [whatsappEndpoints, setWhatsappEndpoints] = useState<WhatsappEndpointOption[]>([])
  const [selectedWhatsappEndpointId, setSelectedWhatsappEndpointId] = useState<string>('')
  const [whatsappLinks, setWhatsappLinks] = useState<ThreadWhatsappLink[]>([])
  const [showLinkChatModal, setShowLinkChatModal] = useState(false)
  const [unlinkingId, setUnlinkingId] = useState<number | null>(null)
  const [resyncingId, setResyncingId] = useState<number | null>(null)
  const [resyncResults, setResyncResults] = useState<Record<number, string>>({})
  const [replyTarget, setReplyTarget] = useState<ReplyTarget>(null)
  const [replyMessage, setReplyMessage] = useState('')
  const [replySubject, setReplySubject] = useState('')
  const [replySending, setReplySending] = useState(false)
  const selectedWhatsappEndpoint = whatsappEndpoints.find((endpoint) => String(endpoint.id) === selectedWhatsappEndpointId) ?? null
  const hasWhatsappEndpoints = whatsappEndpoints.length > 0

  useEffect(() => {
    if (!tenantId) {
      setTenant(null)
      setItems([])
      setError('Select a tenant')
      setSelectedWhatsappGroup(null)
      setWhatsappEndpoints([])
      setSelectedWhatsappEndpointId('')
      setWhatsappLinks([])
      return
    }

    const controller = new AbortController()

    const loadThread = async () => {
      try {
        setLoading(true)
        setError('')
        const [tenantResponse, threadResponse, endpointResponse, linksResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/tenants/${tenantId}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
          fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/grouped-thread`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
          fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/whatsapp-endpoints`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
          fetch(`${API_BASE_URL}/api/threads/${tenantId}/whatsapp-links`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
        ])

        if (!tenantResponse.ok || !threadResponse.ok || !endpointResponse.ok) {
          throw new Error('Failed to load thread')
        }

        const tenantData: TenantSummary = await tenantResponse.json()
        const groupedThreadData: GroupedThreadResponse = await threadResponse.json()
        const endpointData: WhatsappEndpointOption[] = await endpointResponse.json()
        setTenant(tenantData)
        setItems(groupedThreadData.items)
        setWhatsappEndpoints(endpointData)
        setSelectedWhatsappEndpointId((current) => {
          if (current && endpointData.some((endpoint) => String(endpoint.id) === current)) {
            return current
          }
          return endpointData.length === 1 ? String(endpointData[0].id) : ''
        })
        if (linksResponse.ok) {
          const linksData: ThreadWhatsappLink[] = await linksResponse.json()
          setWhatsappLinks(Array.isArray(linksData) ? linksData : [])
        }
        setExpandedConversationIds([])
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load thread')
      } finally {
        setLoading(false)
      }
    }

    loadThread()
    return () => controller.abort()
  }, [tenantId, token, reloadSignal])

  useEffect(() => {
    if (!selectedWhatsappGroup) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSelectedWhatsappGroup(null)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedWhatsappGroup])

  useEffect(() => {
    if (!selectedWhatsappGroup) return
    const scrollContainer = document.querySelector('[data-whatsapp-messages]')
    if (scrollContainer) {
      setTimeout(() => {
        scrollContainer.scrollTop = scrollContainer.scrollHeight
      }, 0)
    }
  }, [selectedWhatsappGroup, replyTarget?.type])

  const toggleConversation = (conversationId: number) => {
    setExpandedConversationIds((current) =>
      current.includes(conversationId) ? current.filter((id) => id !== conversationId) : [...current, conversationId],
    )
  }

  const toggleWhatsappBlock = (blockId: string) => {
    setExpandedWhatsappBlockIds((current) =>
      current.includes(blockId) ? current.filter((id) => id !== blockId) : [...current, blockId],
    )
  }

  const openWhatsappGroup = (group: WhatsappGroupItem) => {
    setSelectedWhatsappGroup(group)
  }

  const loadGroupedThread = async () => {
    if (!tenantId) return

    const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/grouped-thread`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })

    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail || 'Failed to load thread')
    }

    const groupedThreadData: GroupedThreadResponse = await response.json()
    setItems(groupedThreadData.items)
    setSelectedWhatsappGroup((current) => {
      if (!current) return current
      const refreshedGroup = groupedThreadData.items.find((item): item is WhatsappGroupItem => item.type === 'whatsapp_group' && item.group_id === current.group_id)
      return refreshedGroup || current
    })
  }

  const reloadWhatsappLinks = async () => {
    if (!tenantId) return
    const response = await fetch(`${API_BASE_URL}/api/threads/${tenantId}/whatsapp-links`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!response.ok) return
    const data: ThreadWhatsappLink[] = await response.json()
    setWhatsappLinks(Array.isArray(data) ? data : [])
  }

  const handleUnlinkWhatsappChat = async (link: ThreadWhatsappLink) => {
    if (!tenantId || unlinkingId) return
    try {
      setUnlinkingId(link.id)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/threads/${tenantId}/whatsapp-links/${link.id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || 'Failed to unlink WhatsApp chat')
      }
      await reloadWhatsappLinks()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to unlink WhatsApp chat')
    } finally {
      setUnlinkingId(null)
    }
  }

  const handleResyncWhatsappChat = async (link: ThreadWhatsappLink) => {
    if (!tenantId || resyncingId) return
    try {
      setResyncingId(link.id)
      setError('')
      setResyncResults((current) => {
        const next = { ...current }
        delete next[link.id]
        return next
      })
      const response = await fetch(`${API_BASE_URL}/api/threads/${tenantId}/whatsapp-links/${link.id}/resync`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      const payload = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(payload?.detail || 'Failed to resync WhatsApp chat history')
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
        [link.id]: `Done: ${resync.fetched} fetched, ${resync.imported} imported, ${resync.deduped} already synced${skippedSuffix}`,
      }))
      await reloadWhatsappLinks()
      await loadGroupedThread()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resync WhatsApp chat history')
    } finally {
      setResyncingId(null)
    }
  }

  const handleSendReply = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!tenantId || !replyMessage.trim() || replySending || !replyTarget) return

    try {
      setReplySending(true)
      setError('')

      if (replyTarget.type === 'email') {
        const requestBody = {
          channel: 'email',
          subject: replySubject.trim() || replyTarget.subject || '',
          message: replyMessage,
          email_thread_id: replyTarget.threadId,
        }
        const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/send`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(requestBody),
        })
        if (!response.ok) {
          const payload = await response.json().catch(() => null)
          console.error('[crm] Email send error:', { status: response.status, payload })
          throw new Error(payload?.detail || 'Failed to send email')
        }
      } else if (replyTarget.type === 'whatsapp') {
        if (!selectedWhatsappEndpointId) {
          throw new Error('Choose a WhatsApp account before sending')
        }
        const requestBody = {
          channel: 'whatsapp',
          message: replyMessage,
          whatsapp_endpoint_id: Number(selectedWhatsappEndpointId),
          external_account_id: selectedWhatsappEndpoint?.external_account_id ?? null,
        }
        const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/send`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(requestBody),
        })
        if (!response.ok) {
          const payload = await response.json().catch(() => null)
          throw new Error(payload?.detail || 'Failed to send WhatsApp message')
        }
      }

      await loadGroupedThread()
      setReplyMessage('')
      setReplySubject('')
      if (replyTarget.type === 'whatsapp') {
        setSelectedWhatsappGroup(null)
      }
      setReplyTarget(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message')
    } finally {
      setReplySending(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 min-h-[680px] flex-col rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-200 px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">{tenant ? tenant.name : 'Messages'}</h2>
            <p className="mt-1 text-sm text-gray-500">
              {tenant ? [tenant.email || 'No email on file', tenant.phone || 'No phone on file'].join(' � ') : 'Select a tenant'}
            </p>
          </div>
          {tenantId ? (
            <button
              type="button"
              onClick={() => setShowLinkChatModal(true)}
              className="shrink-0 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-100"
            >
              Link chat
            </button>
          ) : null}
        </div>

        {whatsappLinks.filter((link) => link.is_active).length > 0 ? (
          <div className="mt-3 space-y-2">
            {whatsappLinks
              .filter((link) => link.is_active)
              .map((link) => (
                <div key={link.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2">
                  <div className="min-w-0">
                    <p className="text-[11px] uppercase tracking-[0.24em] text-emerald-700">Linked WhatsApp chat - {link.external_account_id}</p>
                    <p className="truncate font-mono text-sm font-semibold text-gray-900">{link.chat_id}</p>
                    <p className="text-xs text-gray-600">
                      {link.chat_display_name || 'No name'} - linked {formatDisplayDate(link.created_at)}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={resyncingId === link.id}
                      onClick={() => handleResyncWhatsappChat(link)}
                      title="Pull the chat's entire history again (fixes chats that were only partially synced)"
                      className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:text-gray-900 disabled:opacity-50"
                    >
                      {resyncingId === link.id ? 'Resyncing...' : 'Resync full history'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowLinkChatModal(true)}
                      className="rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:text-gray-900"
                    >
                      Replace
                    </button>
                    <button
                      type="button"
                      disabled={unlinkingId === link.id}
                      onClick={() => handleUnlinkWhatsappChat(link)}
                      className="rounded-lg border border-rose-200 bg-white px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                    >
                      {unlinkingId === link.id ? 'Unlinking...' : 'Unlink'}
                    </button>
                    </div>
                    {resyncResults[link.id] ? <p className="text-xs text-emerald-700">{resyncResults[link.id]}</p> : null}
                  </div>
                </div>
              ))}
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 [scrollbar-width:thin] [scrollbar-color:rgba(6,182,212,0.35)_transparent]">
        {loading ? <p className="text-sm text-gray-500">Loading tenant thread...</p> : null}
        {replySending ? <p className="mt-1 text-sm text-gray-500">Sending message...</p> : null}
        {error ? <p className="mb-4 text-sm text-rose-500">{error}</p> : null}

        <div className="space-y-4">
          {items.map((item) => {
            if (item.type === 'email_thread') {
              const expanded = expandedConversationIds.includes(item.id)
              const latestMessage = item.messages[item.messages.length - 1]
              const timelineEntries = [
                ...item.messages.map((messageItem) => ({
                  kind: 'email' as const,
                  timestamp: messageItem.sent_at,
                  messageItem,
                })),
                ...item.whatsapp_blocks.map((block) => ({
                  kind: 'whatsapp_block' as const,
                  timestamp: block.start_at || block.end_at || new Date().toISOString(),
                  block,
                })),
              ].sort((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime())
              return (
                <article key={item.id} className="rounded-2xl border border-gray-200 bg-gray-50">
                  <div
                    onClick={() => toggleConversation(item.id)}
                    className="flex w-full cursor-pointer items-start justify-between gap-4 px-4 py-3 text-left"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-gray-500">
                        <span className="rounded-full bg-cyan-100 px-2 py-1 font-semibold text-cyan-700">Email Thread</span>
                        <span>{formatDisplayDate(item.anchor_timestamp || latestMessage?.sent_at || new Date().toISOString())}</span>
                      </div>
                      <p className="mt-2 truncate text-sm font-semibold text-gray-900">{item.subject || latestMessage?.subject || 'Untitled conversation'}</p>
                      <p className="mt-1 truncate text-sm text-gray-600">{item.messages[0] ? extractPreviewText(item.messages[0]) : 'No preview available'}</p>
                      <p className="mt-2 text-xs font-medium text-gray-500">
                        {item.provider_account_display_name || item.provider_account_email ? `Mailbox: ${item.provider_account_display_name || item.provider_account_email}` : 'Mailbox: unknown'}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-gray-600 shadow-sm">
                        {expanded ? 'Collapse' : `${item.messages.length} messages`}
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          if (!expanded) toggleConversation(item.id)
                          setReplyTarget({ type: 'email', threadId: item.id, providerThreadId: item.provider_thread_id, providerAccountId: item.provider_account_id || 0, subject: item.subject })
                        }}
                        className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                      >
                        Reply
                      </button>
                    </div>
                  </div>

                  {expanded ? (
                    <div className="border-t border-gray-200 bg-white px-4 py-3">
                      <div className="space-y-3">
                        {timelineEntries.map((entry) => {
                          if (entry.kind === 'email') {
                            const messageItem = entry.messageItem
                            const isOutbound = messageItem.direction === 'outbound'
                            return (
                              <article key={`email-${messageItem.id}`} className={`max-w-[92%] rounded-2xl border px-4 py-3 ${isOutbound ? 'ml-auto border-cyan-200 bg-cyan-50' : 'border-amber-200 bg-amber-50'}`}>
                                <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-gray-500">
                                  <span className={`rounded-full px-2 py-1 font-semibold ${isOutbound ? 'bg-cyan-100 text-cyan-700' : 'bg-amber-100 text-amber-700'}`}>
                                    {isOutbound ? 'Outbound' : 'Inbound'}
                                  </span>
                                  <span>{formatDisplayDate(messageItem.sent_at)}</span>
                                  <span className="normal-case tracking-normal">
                                    {item.provider_account_display_name || item.provider_account_email ? `Mailbox: ${item.provider_account_display_name || item.provider_account_email}` : 'Mailbox: unknown'}
                                  </span>
                                </div>
                                {messageItem.subject ? <p className="mt-2 text-sm font-semibold text-gray-900">{messageItem.subject}</p> : null}
                                {renderMessageBody(messageItem) ? (<div className="prose prose-sm max-w-none mt-2 overflow-x-auto text-sm leading-6 text-gray-700 prose-p:my-2 prose-a:text-cyan-700 prose-a:underline prose-blockquote:border-gray-300 prose-blockquote:pl-4 prose-blockquote:text-gray-600" dangerouslySetInnerHTML={renderMessageBody(messageItem)} />) : (<p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">{messageItem.body_text || messageItem.body}</p>)}
                              </article>
                            )
                          }

                          const block = entry.block
                          const blockExpanded = expandedWhatsappBlockIds.includes(block.block_id)
                          const firstBlockMessage = block.messages[0]
                          const lastBlockMessage = block.messages[block.messages.length - 1]
                          return (
                            <article key={`whatsapp-${block.block_id}`} className="rounded-2xl border border-emerald-200 bg-emerald-50">
                              <button
                                type="button"
                                onClick={() => toggleWhatsappBlock(block.block_id)}
                                className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left"
                              >
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-emerald-700">
                                    <span className="rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-800">WhatsApp</span>
                                    <span>{formatDisplayDate(block.start_at || firstBlockMessage?.sent_at || lastBlockMessage?.sent_at || new Date().toISOString())}</span>
                                  </div>
                                  <p className="mt-2 truncate text-sm font-semibold text-gray-900">
                                    {block.message_count === 1 ? '1 message' : `${block.message_count} messages`}
                                  </p>
                                  <p className="mt-1 truncate text-sm text-gray-600">
                                    {blockExpanded ? 'Tap to collapse WhatsApp bubbles' : 'Tap to expand WhatsApp bubbles'}
                                  </p>
                                </div>
                                <span className="mt-1 rounded-full bg-white px-2 py-1 text-xs font-semibold text-emerald-700 shadow-sm">
                                  {blockExpanded ? 'Collapse' : 'Expand'}
                                </span>
                              </button>

                              {blockExpanded ? (
                                <div className="border-t border-emerald-200 bg-white px-4 py-3">
                                  <div className="space-y-3">
                                    {block.messages.map((blockMessage) => {
                                      const isOutbound = blockMessage.direction === 'outbound'
                                      return (
                                        <article key={blockMessage.id} className={`max-w-[92%] rounded-2xl border px-4 py-3 ${isOutbound ? 'ml-auto border-cyan-200 bg-cyan-50' : 'border-amber-200 bg-amber-50'}`}>
                                          <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-gray-500">
                                            <span className={`rounded-full px-2 py-1 font-semibold ${isOutbound ? 'bg-cyan-100 text-cyan-700' : 'bg-amber-100 text-amber-700'}`}>
                                              {isOutbound ? 'Outbound' : 'Inbound'}
                                            </span>
                                            <span>{formatDisplayDate(blockMessage.sent_at)}</span>
                                            <span className="normal-case tracking-normal">Account: {blockMessage.external_account_id || blockMessage.external_phone_id || blockMessage.whatsapp_chat_id || 'unknown'}</span>
                                          </div>
                                          {blockMessage.subject ? <p className="mt-2 text-sm font-semibold text-gray-900">{blockMessage.subject}</p> : null}
                                          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">{blockMessage.body}</p>
                                        </article>
                                      )
                                    })}
                                  </div>
                                </div>
                              ) : null}
                            </article>
                          )
                        })}
                      </div>
                    </div>
                  ) : null}
                </article>
              )
            }

            const firstMessage = item.messages[0]
            const lastMessage = item.messages[item.messages.length - 1]
            return (
              <article key={item.group_id} className="rounded-2xl border border-emerald-200 bg-emerald-50">
                <div
                  onClick={() => openWhatsappGroup(item)}
                  className="flex w-full cursor-pointer items-start justify-between gap-4 px-4 py-3 text-left transition hover:bg-emerald-100/70"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-emerald-700">
                      <span className="rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-800">WhatsApp Group</span>
                      <span>{formatDisplayDate(item.start_timestamp || firstMessage?.created_at || lastMessage?.created_at || new Date().toISOString())}</span>
                    </div>
                    <p className="mt-2 truncate text-sm font-semibold text-gray-900">
                      {item.messages.length === 1 ? 'WhatsApp message' : `WhatsApp messages (${item.message_count})`}
                    </p>
                    <p className="mt-1 truncate text-sm text-gray-600">{item.messages[0] ? extractWhatsappPreviewText(item.messages[0]) : 'No preview available'}</p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-2">
                    <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-emerald-700 shadow-sm">
                      {item.message_count} messages
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setSelectedWhatsappGroup(item)
                        setReplyTarget({ type: 'whatsapp', groupId: item.group_id })
                      }}
                      className="rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-50"
                    >
                      Reply
                    </button>
                  </div>
                </div>
              </article>
            )
          })}
          {!items.length && !loading ? <p className="text-sm text-gray-500">No tenant thread items synced yet.</p> : null}
        </div>
      </div>


      {selectedWhatsappGroup ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/45 px-4 backdrop-blur-sm"
          onClick={() => setSelectedWhatsappGroup(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="whatsapp-group-modal-title"
            className="w-full max-w-2xl rounded-3xl border border-gray-200 bg-white shadow-sm"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-6 py-5">
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-[0.35em] text-emerald-700">WhatsApp Group</p>
                <h3 id="whatsapp-group-modal-title" className="mt-1 truncate text-2xl font-semibold text-gray-900">
                  {tenant?.name || 'WhatsApp conversation'}
                </h3>
                <p className="mt-1 text-sm text-gray-500">
                  {formatDisplayDate(selectedWhatsappGroup.start_timestamp || selectedWhatsappGroup.messages[0]?.created_at || selectedWhatsappGroup.messages[selectedWhatsappGroup.messages.length - 1]?.created_at || new Date().toISOString())}
                  {selectedWhatsappGroup.end_timestamp ? ` ? ${formatDisplayDate(selectedWhatsappGroup.end_timestamp)}` : ''}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedWhatsappGroup(null)}
                className="rounded-xl px-3 py-2 text-sm font-semibold text-gray-500 hover:bg-gray-100 hover:text-gray-900"
              >
                Close
              </button>
            </div>

            <div className="max-h-[72vh] overflow-y-auto px-6 py-5" data-whatsapp-messages>
              <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.28em] text-emerald-700">Messages</p>
                  <p className="mt-1 text-sm font-semibold text-gray-900">
                    {selectedWhatsappGroup.message_count === 1 ? '1 message' : `${selectedWhatsappGroup.message_count} messages`}
                  </p>
                </div>
                <p className="text-xs text-gray-500">
                  {selectedWhatsappGroup.start_timestamp && selectedWhatsappGroup.end_timestamp
                    ? `${formatDisplayDate(selectedWhatsappGroup.start_timestamp)} - ${formatDisplayDate(selectedWhatsappGroup.end_timestamp)}`
                    : 'Latest timestamp shown above'}
                </p>
              </div>

              <div className="space-y-3 mb-4">
                {selectedWhatsappGroup.messages.map((blockMessage) => {
                  const isOutbound = blockMessage.direction === 'outbound'
                  return (
                    <article
                      key={blockMessage.id}
                      className={`max-w-[92%] rounded-2xl border px-4 py-3 ${isOutbound ? 'ml-auto border-cyan-200 bg-cyan-50' : 'border-amber-200 bg-amber-50'}`}
                    >
                      <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-gray-500">
                        <span className={`rounded-full px-2 py-1 font-semibold ${isOutbound ? 'bg-cyan-100 text-cyan-700' : 'bg-amber-100 text-amber-700'}`}>
                          {isOutbound ? 'Outbound' : 'Inbound'}
                        </span>
                        <span>{formatDisplayDate(blockMessage.created_at)}</span>
                        <span className="normal-case tracking-normal">Account: {blockMessage.external_account_id || blockMessage.external_phone_id || blockMessage.whatsapp_chat_id || 'unknown'}</span>
                      </div>
                      {blockMessage.subject ? <p className="mt-2 text-sm font-semibold text-gray-900">{blockMessage.subject}</p> : null}
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">{blockMessage.message}</p>
                    </article>
                  )
                })}
              </div>

              {replyTarget?.type === 'whatsapp' && replyTarget.groupId === selectedWhatsappGroup.group_id ? (
                <form onSubmit={handleSendReply} className="space-y-3 rounded-xl border border-cyan-200 bg-cyan-50 p-4">
                  <div className="space-y-2">
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="modal-whatsapp-endpoint">
                      WhatsApp account
                    </label>
                    <select
                      id="modal-whatsapp-endpoint"
                      value={selectedWhatsappEndpointId}
                      onChange={(event) => setSelectedWhatsappEndpointId(event.target.value)}
                      disabled={replySending || !hasWhatsappEndpoints}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
                    >
                      <option value="">{hasWhatsappEndpoints ? 'Choose an account' : 'No active WhatsApp accounts'}</option>
                      {whatsappEndpoints.map((endpoint) => (
                        <option key={endpoint.id} value={endpoint.id}>
                          {formatWhatsappEndpointLabel(endpoint)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <textarea
                    value={replyMessage}
                    onChange={(event) => setReplyMessage(event.target.value)}
                    rows={3}
                    placeholder="Write your reply..."
                    disabled={replySending}
                    className="w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
                  />
                  <div className="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setReplyTarget(null)}
                      className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={replySending || !replyMessage.trim() || !selectedWhatsappEndpointId}
                      className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {replySending ? 'Sending...' : 'Send'}
                    </button>
                  </div>
                </form>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {replyTarget?.type === 'email' ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/45 px-4 backdrop-blur-sm"
          onClick={() => setReplyTarget(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="email-reply-modal-title"
            className="w-full max-w-2xl rounded-3xl border border-gray-200 bg-white shadow-sm"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-4 border-b border-gray-200 px-6 py-5">
              <h3 id="email-reply-modal-title" className="text-lg font-semibold text-gray-900">
                Reply to Email
              </h3>
              <button
                type="button"
                onClick={() => setReplyTarget(null)}
                className="rounded-xl px-3 py-2 text-sm font-semibold text-gray-500 hover:bg-gray-100 hover:text-gray-900"
              >
                Close
              </button>
            </div>

            <form onSubmit={handleSendReply} className="space-y-4 px-6 py-5">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500 mb-2">
                  Subject
                </label>
                <input
                  value={replySubject}
                  onChange={(event) => setReplySubject(event.target.value)}
                  placeholder={replyTarget.subject || 'Subject'}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500 mb-2">
                  Message
                </label>
                <textarea
                  value={replyMessage}
                  onChange={(event) => setReplyMessage(event.target.value)}
                  rows={6}
                  placeholder="Write your reply..."
                  disabled={replySending}
                  className="w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
                />
              </div>

              <div className="flex items-center justify-between gap-3 border-t border-gray-200 pt-4">
                <button
                  type="button"
                  onClick={() => setReplyTarget(null)}
                  className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={replySending || !replyMessage.trim()}
                  className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {replySending ? 'Sending...' : 'Send Reply'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {tenantId ? (
        <LinkChatModal
          open={showLinkChatModal}
          threadId={tenantId}
          onClose={() => setShowLinkChatModal(false)}
          onLinked={reloadWhatsappLinks}
        />
      ) : null}
    </div>
  )
}



