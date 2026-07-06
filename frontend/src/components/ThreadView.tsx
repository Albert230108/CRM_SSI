import { useEffect, useState, type FormEvent } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatDisplayDate } from '../lib/date'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

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
  const [channel, setChannel] = useState<'whatsapp' | 'email'>('whatsapp')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)

  useEffect(() => {
    if (!tenantId) {
      setTenant(null)
      setItems([])
      setError('Select a tenant')
      setSelectedWhatsappGroup(null)
      setWhatsappEndpoints([])
      setSelectedWhatsappEndpointId('')
      return
    }

    const controller = new AbortController()

    const loadThread = async () => {
      try {
        setLoading(true)
        setError('')
        const [tenantResponse, threadResponse, endpointResponse] = await Promise.all([
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

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!tenantId || !message.trim() || sending) return

    try {
      setSending(true)
      setError('')
      if (channel === 'whatsapp' && !selectedWhatsappEndpointId) {
        throw new Error('Choose a WhatsApp account before sending')
      }

      if (channel === 'whatsapp') {
        await loadGroupedThread()
      }

      const requestBody = {
        channel,
        subject: subject.trim() || null,
        message,
        whatsapp_endpoint_id: channel === 'whatsapp' ? Number(selectedWhatsappEndpointId) : null,
      }
      console.info('[crm] ThreadView outbound send request', {
        path: `/api/communications/tenants/${tenantId}/send`,
        tenant_id: tenantId,
        body: requestBody,
      })

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
        throw new Error(payload?.detail || 'Failed to send message')
      }

      await loadGroupedThread()
      setMessage('')
      if (channel === 'email') {
        setSubject('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 min-h-[680px] flex-col rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-200 px-5 py-4">
        <h2 className="text-xl font-semibold text-gray-900">{tenant ? tenant.name : 'Messages'}</h2>
        <p className="mt-1 text-sm text-gray-500">
          {tenant ? [tenant.email || 'No email on file', tenant.phone || 'No phone on file'].join(' � ') : 'Select a tenant'}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 [scrollbar-width:thin] [scrollbar-color:rgba(6,182,212,0.35)_transparent]">
        {loading ? <p className="text-sm text-gray-500">Loading tenant thread...</p> : null}
        {sending ? <p className="mt-1 text-sm text-gray-500">Sending message...</p> : null}
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
                  <button
                    type="button"
                    onClick={() => toggleConversation(item.id)}
                    className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left"
                  >
                    <div className="min-w-0">
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
                    <span className="mt-1 rounded-full bg-white px-2 py-1 text-xs font-semibold text-gray-600 shadow-sm">
                      {expanded ? 'Collapse' : `${item.messages.length} messages`}
                    </span>
                  </button>

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
                <button
                  type="button"
                  onClick={() => openWhatsappGroup(item)}
                  className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left transition hover:bg-emerald-100/70"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-emerald-700">
                      <span className="rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-800">WhatsApp Group</span>
                      <span>{formatDisplayDate(item.start_timestamp || firstMessage?.created_at || lastMessage?.created_at || new Date().toISOString())}</span>
                    </div>
                    <p className="mt-2 truncate text-sm font-semibold text-gray-900">
                      {item.messages.length === 1 ? 'WhatsApp message' : `WhatsApp messages (${item.message_count})`}
                    </p>
                    <p className="mt-1 truncate text-sm text-gray-600">{item.messages[0] ? extractWhatsappPreviewText(item.messages[0]) : 'No preview available'}</p>
                  </div>
                  <span className="mt-1 rounded-full bg-white px-2 py-1 text-xs font-semibold text-emerald-700 shadow-sm">
                    {item.message_count} messages
                  </span>
                </button>
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

            <div className="max-h-[72vh] overflow-y-auto px-6 py-5">
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

              <div className="space-y-3">
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
            </div>
          </div>
        </div>
      ) : null}

      <form onSubmit={handleSend} className="border-t border-gray-200 p-4">
        <div className="flex w-full gap-2">
          <button type="button" onClick={() => setChannel('whatsapp')} disabled={sending} className={`flex-1 rounded-full px-3 py-1.5 text-center text-sm font-semibold ${channel === 'whatsapp' ? 'bg-cyan-600 text-white' : 'bg-gray-100 text-gray-700'} disabled:cursor-not-allowed disabled:opacity-50`}>
            WhatsApp
          </button>
          <button type="button" onClick={() => setChannel('email')} disabled={sending} className={`flex-1 rounded-full px-3 py-1.5 text-center text-sm font-semibold ${channel === 'email' ? 'bg-cyan-600 text-white' : 'bg-gray-100 text-gray-700'} disabled:cursor-not-allowed disabled:opacity-50`}>
            Email
          </button>
        </div>

        {channel === 'email' ? (
          <input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="Subject"
            className="mt-3 w-full rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
          />
        ) : null}

        {channel === 'whatsapp' ? (
          <div className="mt-3 space-y-2">
            <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="whatsapp-endpoint-selector">
              WhatsApp account
            </label>
            <select
              id="whatsapp-endpoint-selector"
              value={selectedWhatsappEndpointId}
              onChange={(event) => setSelectedWhatsappEndpointId(event.target.value)}
              disabled={sending || !whatsappEndpoints.length}
              className="w-full rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
            >
              <option value="">Choose an account</option>
              {whatsappEndpoints.map((endpoint) => (
                <option key={endpoint.id} value={endpoint.id}>
                  {endpoint.external_account_id || `Endpoint ${endpoint.id}`}{endpoint.external_phone_id ? ` - ${endpoint.external_phone_id}` : ''}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={4}
          placeholder={channel === 'whatsapp' ? 'Write a WhatsApp message...' : 'Write an email...'}
          disabled={sending}
          className="mt-3 w-full resize-none rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
        />

        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs text-gray-500">{channel === 'whatsapp' ? 'WhatsApp send.' : 'Email reply.'}</p>
          <button type="submit" disabled={sending || loading || !tenantId || !message.trim() || (channel === 'whatsapp' && !selectedWhatsappEndpointId)} className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50">
            {sending ? 'Sending...' : 'Send'}
          </button>
        </div>
      </form>
    </div>
  )
}


