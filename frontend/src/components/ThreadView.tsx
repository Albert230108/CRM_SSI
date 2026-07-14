import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatCombinedDateTime } from '../lib/date'
import { useRelativeTimestampsFirstPreference } from '../lib/displayPreferences'
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
  body_display: string | null
  body_text: string | null
  body_html: string | null
  attachments?: { attachment_id: string; filename: string; mime_type: string | null; size: number | null }[]
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

const QUOTE_CONTAINER_CLASS_PATTERN = /(?:^|\s)(gmail_quote|gmail_quote_container|yahoo_quoted|protonmail_quote|moz-cite-prefix|gmail_attr)(?:\s|$)/i

const removeQuotedReplyElements = (root: HTMLElement) => {
  Array.from(root.querySelectorAll('*')).forEach((node) => {
    if (!node.isConnected) return
    const el = node as HTMLElement
    const isQuoteContainer =
      QUOTE_CONTAINER_CLASS_PATTERN.test(el.className || '') ||
      (el.tagName === 'BLOCKQUOTE' && (el.getAttribute('type') || '').toLowerCase() === 'cite')
    if (isQuoteContainer) el.remove()
  })
}

const sanitizeHtml = (html: string) => {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  removeQuotedReplyElements(doc.body)
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

const extractPreviewText = (message: Pick<TimelineMessage, 'body' | 'body_display' | 'body_text' | 'body_html'>) => {
  if (message.body_html) {
    const doc = new DOMParser().parseFromString(message.body_html, 'text/html')
    removeQuotedReplyElements(doc.body)
    return htmlToPlainText(doc.body.innerHTML).replace(/\s+/g, ' ').trim()
  }
  const source = message.body_text || message.body_display || message.body || ''
  if (!source) return ''
  if (/<[^>]+>/.test(source)) {
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
  thread_id: number
  provider_account_id: number | null
  provider_account_email: string | null
  provider_account_display_name: string | null
  provider_thread_id: string
  subject: string | null
  preview_text: string | null
  anchor_timestamp: string
  messages: TimelineMessage[]
  whatsapp_blocks: {
    block_id: string
    start_at: string | null
    end_at: string | null
    messages: WhatsappTimelineMessage[]
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

type ThreadTimelineEntry =
  | { kind: 'email'; sortTime: number; message: TimelineMessage }
  | { kind: 'whatsapp_block'; sortTime: number; block: EmailThreadItem['whatsapp_blocks'][number] }

const buildThreadTimelineEntries = (thread: EmailThreadItem): ThreadTimelineEntry[] => {
  const entries: ThreadTimelineEntry[] = [
    ...thread.messages.map((message) => ({ kind: 'email' as const, sortTime: new Date(message.sent_at).getTime(), message })),
    ...thread.whatsapp_blocks.map((block) => ({
      kind: 'whatsapp_block' as const,
      sortTime: new Date(block.start_at || block.end_at || block.messages[0]?.created_at || 0).getTime(),
      block,
    })),
  ]
  entries.sort((a, b) => a.sortTime - b.sortTime)
  return entries
}

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
  booking_id?: string | null
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
  const downloadAttachment = useCallback(
    async (messageId: number, attachmentId: string, filename: string) => {
      const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/messages/${messageId}/attachments/${attachmentId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!response.ok) {
        return
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    },
    [token],
  )
  const [relativeTimestampsFirst] = useRelativeTimestampsFirstPreference()
  const formatTimestamp = useCallback((value?: string | number | Date | null) => formatCombinedDateTime(value, relativeTimestampsFirst), [relativeTimestampsFirst])
  const [tenant, setTenant] = useState<TenantSummary | null>(null)
  const [items, setItems] = useState<ThreadItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedWhatsappGroup, setSelectedWhatsappGroup] = useState<WhatsappGroupItem | null>(null)
  const [selectedWhatsappBlock, setSelectedWhatsappBlock] = useState<(EmailThreadItem['whatsapp_blocks'][number] & { threadId: number }) | null>(null)
  const [whatsappEndpoints, setWhatsappEndpoints] = useState<WhatsappEndpointOption[]>([])
  const [selectedWhatsappEndpointId, setSelectedWhatsappEndpointId] = useState<string>('')
  const [whatsappLinks, setWhatsappLinks] = useState<ThreadWhatsappLink[]>([])
  const [showLinkChatModal, setShowLinkChatModal] = useState(false)
  const [replyTarget, setReplyTarget] = useState<ReplyTarget>(null)
  const [replyMessage, setReplyMessage] = useState('')
  const [replySubject, setReplySubject] = useState('')
  const [replySending, setReplySending] = useState(false)
  const [selectedEmailThread, setSelectedEmailThread] = useState<EmailThreadItem | null>(null)
  const selectedWhatsappEndpoint = whatsappEndpoints.find((endpoint) => String(endpoint.id) === selectedWhatsappEndpointId) ?? null
  const hasWhatsappEndpoints = whatsappEndpoints.length > 0
  const [livePollSignal, setLivePollSignal] = useState(0)

  useEffect(() => {
    if (!tenantId) return

    let cancelled = false
    let lastSeenVersion: string | null = null

    const pollThreadVersion = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/thread-version`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (!response.ok || cancelled) return
        const data: { latest_at: string | null } = await response.json()
        if (lastSeenVersion === null) {
          lastSeenVersion = data.latest_at
          return
        }
        if (data.latest_at !== lastSeenVersion) {
          lastSeenVersion = data.latest_at
          setLivePollSignal((current) => current + 1)
        }
      } catch {
        // Ignore transient poll failures; next interval tick will retry.
      }
    }

    const intervalId = window.setInterval(pollThreadVersion, 7000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [tenantId, token])

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
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load thread')
      } finally {
        setLoading(false)
      }
    }

    loadThread()
    return () => controller.abort()
  }, [tenantId, token, reloadSignal, livePollSignal])

  useEffect(() => {
    if (!selectedWhatsappGroup && !selectedEmailThread) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSelectedWhatsappGroup(null)
        setSelectedEmailThread(null)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedWhatsappGroup, selectedEmailThread])

  useEffect(() => {
    if (!selectedWhatsappGroup && !selectedEmailThread) return
    const scrollContainer = selectedEmailThread
      ? document.querySelector('[data-email-messages]')
      : document.querySelector('[data-whatsapp-messages]')
    if (scrollContainer) {
      setTimeout(() => {
        scrollContainer.scrollTop = scrollContainer.scrollHeight
      }, 0)
    }
  }, [selectedWhatsappGroup, selectedEmailThread, replyTarget?.type])

  const openWhatsappGroup = (group: WhatsappGroupItem) => {
    setSelectedWhatsappGroup(group)
  }

  const openEmailThread = (thread: EmailThreadItem) => {
    setSelectedEmailThread(thread)
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
    setSelectedEmailThread((current) => {
      if (!current) return current
      const refreshedThread = groupedThreadData.items.find((item): item is EmailThreadItem => item.type === 'email_thread' && item.thread_id === current.thread_id)
      return refreshedThread || current
    })
    setSelectedWhatsappBlock((current) => {
      if (!current) return current
      const refreshedThread = groupedThreadData.items.find((item): item is EmailThreadItem => item.type === 'email_thread' && item.thread_id === current.threadId)
      const refreshedBlock = refreshedThread?.whatsapp_blocks.find((block) => block.block_id === current.block_id)
      return refreshedBlock ? { ...refreshedBlock, threadId: current.threadId } : current
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

  const handleWhatsappLinksChanged = async () => {
    await reloadWhatsappLinks()
    await loadGroupedThread()
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
        console.info('[crm] Email reply request:', { tenantId, replyTarget, requestBody })
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
          console.error('[crm] Email send error:', { status: response.status, payload, requestBody })
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
        setSelectedWhatsappBlock(null)
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
      <div className="border-b border-gray-200 px-4 py-3">
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
              {whatsappLinks.some((link) => link.is_active) ? 'Manage chats' : 'Link chat'}
            </button>
          ) : null}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 [scrollbar-width:thin] [scrollbar-color:rgba(6,182,212,0.35)_transparent]">
        {loading ? <p className="text-sm text-gray-500">Loading tenant thread...</p> : null}
        {replySending ? <p className="mt-1 text-sm text-gray-500">Sending message...</p> : null}
        {error ? <p className="mb-4 text-sm text-rose-500">{error}</p> : null}

        <div className="space-y-4">
          {items.map((item) => {
            if (item.type === 'email_thread') {
              const latestMessage = item.messages[item.messages.length - 1]
              return (
                <article key={item.thread_id} className="rounded-2xl border border-gray-200 bg-gray-50">
                  <div
                    onClick={() => openEmailThread(item)}
                    className="flex w-full cursor-pointer items-start justify-between gap-4 px-3 py-2.5 text-left transition hover:bg-gray-100/50"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-gray-500">
                        <span className="rounded-full bg-cyan-100 px-2 py-1 font-semibold text-cyan-700">Email Thread</span>
                        <span>{formatTimestamp(item.anchor_timestamp || latestMessage?.sent_at || new Date().toISOString())}</span>
                      </div>
                      <p className="mt-2 truncate text-sm font-semibold text-gray-900">{item.subject || latestMessage?.subject || 'Untitled conversation'}</p>
                      <p className="mt-1 truncate text-sm text-gray-600">{item.messages[0] ? extractPreviewText(item.messages[0]) : 'No preview available'}</p>
                      <p className="mt-2 text-xs font-medium text-gray-500">
                        {item.provider_account_display_name || item.provider_account_email ? `Mailbox: ${item.provider_account_display_name || item.provider_account_email}` : 'Mailbox: unknown'}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-gray-600 shadow-sm">
                        {item.messages.length} messages
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          openEmailThread(item)
                          setReplyTarget({ type: 'email', threadId: item.thread_id, providerThreadId: item.provider_thread_id, providerAccountId: item.provider_account_id || 0, subject: item.subject })
                        }}
                        className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                      >
                        Reply
                      </button>
                    </div>
                  </div>
                </article>
              )
            }

            const firstMessage = item.messages[0]
            const lastMessage = item.messages[item.messages.length - 1]
            return (
              <article key={item.group_id} className="rounded-2xl border border-emerald-200 bg-emerald-50">
                <div
                  onClick={() => openWhatsappGroup(item)}
                  className="flex w-full cursor-pointer items-start justify-between gap-4 px-3 py-2.5 text-left transition hover:bg-emerald-100/70"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-emerald-700">
                      <span className="rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-800">WhatsApp Group</span>
                      <span>{formatTimestamp(item.end_timestamp || lastMessage?.created_at || firstMessage?.created_at || new Date().toISOString())}</span>
                    </div>
                    <p className="mt-2 truncate text-sm font-semibold text-gray-900">
                      {item.messages.length === 1 ? 'WhatsApp message' : `WhatsApp messages (${item.message_count})`}
                    </p>
                    <p className="mt-1 truncate text-sm text-gray-600">{lastMessage ? extractWhatsappPreviewText(lastMessage) : 'No preview available'}</p>
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


      {selectedEmailThread ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center gap-4 bg-gray-900/45 px-4 backdrop-blur-sm"
          onClick={() => {
            setSelectedEmailThread(null)
            setSelectedWhatsappBlock(null)
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="email-thread-modal-title"
            className="w-full max-w-2xl rounded-3xl border border-gray-200 bg-white shadow-sm"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-[0.35em] text-cyan-700">Email Thread</p>
                <h3 id="email-thread-modal-title" className="mt-1 truncate text-2xl font-semibold text-gray-900">
                  {selectedEmailThread.subject || 'Untitled conversation'}
                </h3>
                <p className="mt-1 text-sm text-gray-500">
                  {formatTimestamp(selectedEmailThread.anchor_timestamp || selectedEmailThread.messages[0]?.sent_at || selectedEmailThread.messages[selectedEmailThread.messages.length - 1]?.sent_at || new Date().toISOString())}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedEmailThread(null)}
                className="rounded-xl px-3 py-2 text-sm font-semibold text-gray-500 hover:bg-gray-100 hover:text-gray-900"
              >
                Close
              </button>
            </div>

            <div className="max-h-[72vh] overflow-y-auto px-5 py-4" data-email-messages>
              <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.28em] text-cyan-700">Messages</p>
                  <p className="mt-1 text-sm font-semibold text-gray-900">
                    {selectedEmailThread.messages.length === 1 ? '1 message' : `${selectedEmailThread.messages.length} messages`}
                  </p>
                </div>
                <p className="text-xs text-gray-500">
                  {selectedEmailThread.provider_account_display_name || selectedEmailThread.provider_account_email ? `Mailbox: ${selectedEmailThread.provider_account_display_name || selectedEmailThread.provider_account_email}` : 'Mailbox: unknown'}
                </p>
              </div>

              <div className="space-y-3 mb-4">
                {buildThreadTimelineEntries(selectedEmailThread).map((entry) => {
                  if (entry.kind === 'email') {
                    const messageItem = entry.message
                    const isOutbound = messageItem.direction === 'outbound'
                    return (
                      <article
                        key={`email-${messageItem.id}`}
                        className={`max-w-[92%] rounded-2xl border px-4 py-3 ${isOutbound ? 'ml-auto border-cyan-200 bg-cyan-50' : 'border-amber-200 bg-amber-50'}`}
                      >
                        <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-gray-500">
                          <span className={`rounded-full px-2 py-1 font-semibold ${isOutbound ? 'bg-cyan-100 text-cyan-700' : 'bg-amber-100 text-amber-700'}`}>
                            {isOutbound ? 'Outbound' : 'Inbound'}
                          </span>
                          <span>{formatTimestamp(messageItem.sent_at)}</span>
                        </div>
                        {messageItem.subject ? <p className="mt-2 text-sm font-semibold text-gray-900">{messageItem.subject}</p> : null}
                        {renderMessageBody(messageItem) ? (
                          <div
                            className="prose prose-sm max-w-none mt-2 overflow-x-auto text-sm leading-6 text-gray-700 prose-p:my-2 prose-a:text-cyan-700 prose-a:underline prose-blockquote:border-gray-300 prose-blockquote:pl-4 prose-blockquote:text-gray-600"
                            dangerouslySetInnerHTML={renderMessageBody(messageItem)}
                          />
                        ) : (
                          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">{messageItem.body_text || messageItem.body_display || messageItem.body}</p>
                        )}
                        {messageItem.attachments && messageItem.attachments.length > 0 ? (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {messageItem.attachments.map((attachment) => (
                              <button
                                key={attachment.attachment_id}
                                type="button"
                                onClick={() => downloadAttachment(messageItem.id, attachment.attachment_id, attachment.filename)}
                                className="rounded-full border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
                              >
                                📎 {attachment.filename}
                              </button>
                            ))}
                          </div>
                        ) : null}
                      </article>
                    )
                  }

                  const block = entry.block
                  const lastBlockMessage = block.messages[block.messages.length - 1]
                  return (
                    <article key={`whatsapp-block-${block.block_id}`} className="rounded-2xl border border-emerald-200 bg-emerald-50">
                      <div
                        onClick={() => setSelectedWhatsappBlock({ ...block, threadId: selectedEmailThread.thread_id })}
                        className="flex w-full cursor-pointer items-start justify-between gap-4 px-4 py-3 text-left transition hover:bg-emerald-100/70"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-emerald-700">
                            <span className="rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-800">WhatsApp</span>
                            <span>{formatTimestamp(block.end_at || lastBlockMessage?.created_at || new Date().toISOString())}</span>
                          </div>
                          <p className="mt-2 truncate text-sm font-semibold text-gray-900">
                            {block.message_count === 1 ? 'WhatsApp message' : `WhatsApp messages (${block.message_count})`}
                          </p>
                          <p className="mt-1 truncate text-sm text-gray-600">{lastBlockMessage ? extractWhatsappPreviewText(lastBlockMessage) : 'No preview available'}</p>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-2">
                          <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-emerald-700 shadow-sm">
                            {block.message_count} messages
                          </span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelectedWhatsappBlock({ ...block, threadId: selectedEmailThread.thread_id })
                              setReplyTarget({ type: 'whatsapp', groupId: block.block_id })
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
              </div>

              {replyTarget?.type === 'email' && replyTarget.threadId === selectedEmailThread.thread_id ? (
                <form onSubmit={handleSendReply} className="space-y-3 rounded-xl border border-cyan-200 bg-cyan-50 p-4">
                  <div className="space-y-2">
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="modal-email-subject">
                      Subject
                    </label>
                    <input
                      id="modal-email-subject"
                      value={replySubject}
                      onChange={(event) => setReplySubject(event.target.value)}
                      placeholder={replyTarget.subject || 'Subject'}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                    />
                  </div>
                  <textarea
                    value={replyMessage}
                    onChange={(event) => setReplyMessage(event.target.value)}
                    rows={4}
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
                      disabled={replySending || !replyMessage.trim()}
                      className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {replySending ? 'Sending...' : 'Send'}
                    </button>
                  </div>
                </form>
              ) : null}
            </div>
          </div>

          {selectedWhatsappBlock && selectedWhatsappBlock.threadId === selectedEmailThread.thread_id ? (
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="whatsapp-block-panel-title"
              className="w-full max-w-md rounded-3xl border border-gray-200 bg-white shadow-sm"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-[0.35em] text-emerald-700">WhatsApp</p>
                  <h3 id="whatsapp-block-panel-title" className="mt-1 truncate text-2xl font-semibold text-gray-900">
                    {tenant?.name || 'WhatsApp conversation'}
                  </h3>
                  <p className="mt-1 text-sm text-gray-500">
                    {formatTimestamp(selectedWhatsappBlock.start_at || selectedWhatsappBlock.messages[0]?.created_at || new Date().toISOString())}
                    {selectedWhatsappBlock.end_at ? ` - ${formatTimestamp(selectedWhatsappBlock.end_at)}` : ''}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedWhatsappBlock(null)}
                  className="rounded-xl px-3 py-2 text-sm font-semibold text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                >
                  Close
                </button>
              </div>

              <div className="max-h-[72vh] overflow-y-auto px-5 py-4" data-whatsapp-block-messages>
                <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.28em] text-emerald-700">Messages</p>
                    <p className="mt-1 text-sm font-semibold text-gray-900">
                      {selectedWhatsappBlock.message_count === 1 ? '1 message' : `${selectedWhatsappBlock.message_count} messages`}
                    </p>
                  </div>
                </div>

                <div className="space-y-3 mb-4">
                  {selectedWhatsappBlock.messages.map((blockMessage) => {
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
                          <span>{formatTimestamp(blockMessage.created_at)}</span>
                          <span className="normal-case tracking-normal">Account: {blockMessage.external_account_id || blockMessage.external_phone_id || blockMessage.whatsapp_chat_id || 'unknown'}</span>
                        </div>
                        {blockMessage.subject ? <p className="mt-2 text-sm font-semibold text-gray-900">{blockMessage.subject}</p> : null}
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">{blockMessage.message}</p>
                      </article>
                    )
                  })}
                </div>

                {replyTarget?.type === 'whatsapp' && replyTarget.groupId === selectedWhatsappBlock.block_id ? (
                  <form onSubmit={handleSendReply} className="space-y-3 rounded-xl border border-cyan-200 bg-cyan-50 p-4">
                    <div className="space-y-2">
                      <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="block-whatsapp-endpoint">
                        WhatsApp account
                      </label>
                      <select
                        id="block-whatsapp-endpoint"
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
          ) : null}
        </div>
      ) : null}

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
            <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-[0.35em] text-emerald-700">WhatsApp Group</p>
                <h3 id="whatsapp-group-modal-title" className="mt-1 truncate text-2xl font-semibold text-gray-900">
                  {tenant?.name || 'WhatsApp conversation'}
                </h3>
                <p className="mt-1 text-sm text-gray-500">
                  {formatTimestamp(selectedWhatsappGroup.start_timestamp || selectedWhatsappGroup.messages[0]?.created_at || selectedWhatsappGroup.messages[selectedWhatsappGroup.messages.length - 1]?.created_at || new Date().toISOString())}
                  {selectedWhatsappGroup.end_timestamp ? ` ? ${formatTimestamp(selectedWhatsappGroup.end_timestamp)}` : ''}
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

            <div className="max-h-[72vh] overflow-y-auto px-5 py-4" data-whatsapp-messages>
              <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.28em] text-emerald-700">Messages</p>
                  <p className="mt-1 text-sm font-semibold text-gray-900">
                    {selectedWhatsappGroup.message_count === 1 ? '1 message' : `${selectedWhatsappGroup.message_count} messages`}
                  </p>
                </div>
                <p className="text-xs text-gray-500">
                  {selectedWhatsappGroup.start_timestamp && selectedWhatsappGroup.end_timestamp
                    ? `${formatTimestamp(selectedWhatsappGroup.start_timestamp)} - ${formatTimestamp(selectedWhatsappGroup.end_timestamp)}`
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
                        <span>{formatTimestamp(blockMessage.created_at)}</span>
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
          tenantName={tenant?.name}
          bookingId={tenant?.booking_id ?? undefined}
          onClose={() => setShowLinkChatModal(false)}
          onChanged={handleWhatsappLinksChanged}
        />
      ) : null}
    </div>
  )
}



