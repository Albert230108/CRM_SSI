import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatCombinedDateTime } from '../lib/date'
import { useRelativeTimestampsFirstPreference } from '../lib/displayPreferences'
import { useDraggablePosition } from '../hooks/useDraggablePosition'
import { useResizableSize } from '../hooks/useResizableSize'
import LinkChatModal from './LinkChatModal'
import RichMessageComposer from './RichMessageComposer'
import FirstWhatsAppMessageModal from './FirstWhatsAppMessageModal'
import EmailLinkModal from './EmailLinkModal'
import TenantBrainQuickChat from './TenantBrainQuickChat'
import { ToastCard, ToastStack } from './Toast'
import AiDraftControls from './AiDraftControls'
import InlineSpinner from './InlineSpinner'
import AttachmentPicker, { type PendingAttachment } from './AttachmentPicker'
import { MAX_EMAIL_TOTAL_BYTES, formatBytes } from '../lib/attachmentLimits'
import { removeQuotedReplyElements, sanitizeHtml } from '../lib/sanitizeHtml'
import { hasComposerContent, type ComposerBodyFormat, whatsappMarkupToHtml } from '../lib/messageFormatting'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/api\/?$/, '').replace(/\/$/, '')

const BLOCK_TAGS = new Set(['ADDRESS', 'ARTICLE', 'BLOCKQUOTE', 'DIV', 'DL', 'DT', 'DD', 'FIELDSET', 'FIGCAPTION', 'FIGURE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'LI', 'OL', 'P', 'PRE', 'SECTION', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'UL'])

type Attachment = {
  attachment_id: string
  filename: string
  mime_type: string | null
  size: number | null
  // 'gmail' attachments are proxied live from Gmail by message id; 'stored' ones are blobs
  // the CRM holds itself and are fetched by their own id.
  source?: 'gmail' | 'stored'
  id?: number | null
}

type TimelineMessage = {
  id: number
  provider: string
  provider_message_id: string
  direction: 'inbound' | 'outbound' | string
  sender_email: string | null
  recipient_email: string | null
  subject: string | null
  cc: string | null
  body: string
  body_display: string | null
  body_text: string | null
  body_html: string | null
  attachments?: Attachment[]
  external_account_id?: string | null
  external_phone_id?: string | null
  whatsapp_chat_id?: string | null
  sent_at: string
  ai_generated?: boolean
}

const AiGeneratedBadge = () => (
  <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-indigo-700" title="Sent automatically by AI, without human review">
    AI
  </span>
)

type AttachmentChipsProps = {
  messageId: number
  attachments?: Attachment[]
  downloadingAttachmentId: string | null
  onDownload: (messageId: number, attachment: Attachment) => void
}

const AttachmentChips = ({ messageId, attachments, downloadingAttachmentId, onDownload }: AttachmentChipsProps) => {
  if (!attachments || attachments.length === 0) return null
  return (
    <div className="mt-1.5 flex flex-wrap gap-2">
      {attachments.map((attachment) => {
        const isDownloading = downloadingAttachmentId === attachment.attachment_id
        return (
          <button
            key={attachment.attachment_id}
            type="button"
            disabled={isDownloading}
            onClick={() => onDownload(messageId, attachment)}
            className="flex items-center gap-1.5 rounded-full border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-wait disabled:opacity-70"
          >
            {isDownloading ? (
              <>
                <InlineSpinner className="text-gray-400" />
                Downloading {attachment.filename}…
              </>
            ) : (
              <>📎 {attachment.filename}</>
            )}
          </button>
        )
      })}
    </div>
  )
}

const MessageJumpNav = ({
  total,
  currentIndex,
  onPrev,
  onNext,
}: {
  total: number
  currentIndex: number
  onPrev: () => void
  onNext: () => void
}) => {
  if (total <= 1) return null
  return (
    <div className="absolute right-3 top-3 z-10 flex flex-col items-center gap-1 rounded-xl border border-gray-200 bg-white/95 p-1 shadow-md backdrop-blur">
      <button
        type="button"
        onClick={onPrev}
        disabled={currentIndex <= 0}
        aria-label="Jump to previous message"
        className="flex h-6 w-6 items-center justify-center rounded-lg text-gray-500 hover:bg-cyan-50 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-30"
      >
        ↑
      </button>
      <span className="select-none text-[10px] font-semibold tabular-nums text-gray-400">
        {currentIndex + 1}/{total}
      </span>
      <button
        type="button"
        onClick={onNext}
        disabled={currentIndex >= total - 1}
        aria-label="Jump to next message"
        className="flex h-6 w-6 items-center justify-center rounded-lg text-gray-500 hover:bg-cyan-50 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-30"
      >
        ↓
      </button>
    </div>
  )
}

const scrollToMessageIndex = (containerSelector: string, index: number) => {
  const container = document.querySelector<HTMLElement>(containerSelector)
  if (!container) return
  const target = container.querySelector<HTMLElement>(`[data-message-index="${index}"]`)
  target?.scrollIntoView({ block: 'start', behavior: 'smooth' })
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
  matched_tenant_email: string | null
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
  mobile?: string | null
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
  chat_display_name: string | null
  routing_strategy: string
  is_active: boolean
  is_most_recent_inbound?: boolean
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

type EmailSyncToast = {
  jobId: string
  email: string
  status: 'running' | 'done' | 'error'
  result?: { accounts_checked: number; accounts_failed: number; conversations_matched: number }
  error?: string
}

const formatMailboxAndTenantEmailLabel = (mailboxLabel: string | null, matchedTenantEmail: string | null) => {
  const mailboxText = mailboxLabel ? `Mailbox: ${mailboxLabel}` : 'Mailbox: unknown'
  return matchedTenantEmail ? `${mailboxText} → Tenant email: ${matchedTenantEmail}` : mailboxText
}

const formatWhatsappEndpointLabel = (endpoint: WhatsappEndpointOption) => {
  const parts = [endpoint.external_account_id || `Endpoint ${endpoint.id}`]
  // A tenant can have several chats linked on the same account, so the chat identity (not just
  // the account) has to be in the label -- otherwise the dropdown shows duplicate-looking rows
  // with no way to tell which chat each one actually sends to.
  if (endpoint.chat_display_name) parts.push(endpoint.chat_display_name)
  else if (endpoint.external_chat_namespace) parts.push(endpoint.external_chat_namespace)
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
  ai_generated?: boolean
  attachments?: Attachment[]
}

// Distinct hue per linked WhatsApp account; darker shade = outbound, lighter shade = inbound.
// Direction is also encoded by bubble alignment, so this is a secondary (not sole) signal.
type WhatsappAccountPalette = {
  outboundBubble: string
  outboundBadge: string
  inboundBubble: string
  inboundBadge: string
  dot: string
}

const WHATSAPP_ACCOUNT_PALETTES: WhatsappAccountPalette[] = [
  {
    outboundBubble: 'ml-auto border-green-300 bg-green-100',
    outboundBadge: 'bg-green-200 text-green-900',
    inboundBubble: 'border-green-200 bg-green-50',
    inboundBadge: 'bg-green-100 text-green-700',
    dot: 'bg-green-500',
  },
  {
    outboundBubble: 'ml-auto border-violet-300 bg-violet-100',
    outboundBadge: 'bg-violet-200 text-violet-900',
    inboundBubble: 'border-violet-200 bg-violet-50',
    inboundBadge: 'bg-violet-100 text-violet-700',
    dot: 'bg-violet-500',
  },
  {
    outboundBubble: 'ml-auto border-orange-300 bg-orange-100',
    outboundBadge: 'bg-orange-200 text-orange-900',
    inboundBubble: 'border-orange-200 bg-orange-50',
    inboundBadge: 'bg-orange-100 text-orange-700',
    dot: 'bg-orange-500',
  },
  {
    outboundBubble: 'ml-auto border-sky-300 bg-sky-100',
    outboundBadge: 'bg-sky-200 text-sky-900',
    inboundBubble: 'border-sky-200 bg-sky-50',
    inboundBadge: 'bg-sky-100 text-sky-700',
    dot: 'bg-sky-500',
  },
]

const getWhatsappMessageAccountKey = (message: WhatsappTimelineMessage) =>
  message.external_account_id || message.external_phone_id || message.whatsapp_chat_id || 'unknown'

// Fixed identity -> color/label mapping so an account looks the same on every tenant's thread,
// rather than being colored by the order it happened to get linked on a given tenant.
// external_account_id values come from each whatsapp-service instance's WHATSAPP_CLIENT_ID.
const WHATSAPP_ACCOUNT_DIRECTORY: Record<string, { label: string; paletteIndex: number }> = {
  'ssi-crm-whatsapp': { label: 'SSI-Whatsapp', paletteIndex: 0 }, // green
  'edi-crm-whatsapp': { label: 'EDI-Whatsapp', paletteIndex: 1 }, // violet
}

type ThreadViewProps = {
  tenantId?: number
  reloadSignal?: number
  onReady?: (tenantId: number) => void
  onTenantLoaded?: (tenantName: string) => void
  // Set when the panel was opened from a notification click, so the specific email thread or
  // WhatsApp group that notification was about gets auto-selected once threads finish loading.
  initialThreadTarget?: { channel: string; threadRef: string } | null
  onInitialThreadTargetConsumed?: () => void
}

type ReplyTarget =
  | { type: 'email'; threadId: number; providerThreadId: string; providerAccountId: number; subject: string | null }
  | { type: 'whatsapp'; groupId: string }
  | null

type ForwardTarget = { threadId: number; providerThreadId: string; subject: string | null } | null

type ReplyDraftAttachmentRead = {
  id: number
  filename: string
  size_bytes: number
  mime_type: string | null
}

type ReplyDraftEntry = {
  subject: string
  body: string
  body_html: string | null
  body_format: ComposerBodyFormat
  attachment_ids: number[]
}

const EMPTY_REPLY_DRAFT: ReplyDraftEntry = { subject: '', body: '', body_html: null, body_format: 'plain', attachment_ids: [] }
// Stable identity so the empty case doesn't produce a new array on every render.
const EMPTY_ATTACHMENTS: PendingAttachment[] = []

// Holds a WhatsApp draft typed before an account was picked. Transient and never persisted -
// there is no linked chat to key it to yet; it migrates to the real key once one is selected.
const WHATSAPP_PENDING_DRAFT_KEY = 'whatsapp:pending'

const emailDraftKey = (threadId: number) => `email:${threadId}`
const whatsappDraftKey = (endpointId: number | string) => `whatsapp:${endpointId}`

// Reply drafts are scoped to one email thread or one linked WhatsApp chat, never to the tenant
// as a whole, so a draft can never surface in another thread's - or another tenant's - reply box.
const draftKeyForTarget = (target: ReplyTarget, whatsappEndpointId: string): string | null => {
  if (!target) return null
  if (target.type === 'email') return emailDraftKey(target.threadId)
  return whatsappEndpointId ? whatsappDraftKey(whatsappEndpointId) : WHATSAPP_PENDING_DRAFT_KEY
}

type ReplyDraftRead = {
  id: number
  tenant_id: number
  channel: string
  email_thread_id: number | null
  whatsapp_endpoint_id: number | null
  subject: string | null
  body: string
  body_html: string | null
  body_format: ComposerBodyFormat
  attachment_ids: number[]
  attachments: ReplyDraftAttachmentRead[]
}

const REPLY_DRAFT_AUTOSAVE_DELAY_MS = 800

// JSON rather than concatenation so a subject/body split cannot alias a different pair.
const serializeReplyDraft = (entry: ReplyDraftEntry) => JSON.stringify([entry.subject, entry.body, entry.body_html, entry.body_format, entry.attachment_ids])

// Turns a local draft key back into the scope the API validates against the tenant. Returns null
// for the transient pending-WhatsApp key, which has no linked chat and so is never persisted.
const replyDraftScopeParams = (
  key: string,
): { channel: string; email_thread_id?: number; whatsapp_endpoint_id?: number } | null => {
  if (key.startsWith('email:')) {
    const threadId = Number(key.slice('email:'.length))
    return Number.isFinite(threadId) ? { channel: 'email', email_thread_id: threadId } : null
  }
  if (key === WHATSAPP_PENDING_DRAFT_KEY) return null
  if (key.startsWith('whatsapp:')) {
    const endpointId = Number(key.slice('whatsapp:'.length))
    return Number.isFinite(endpointId) ? { channel: 'whatsapp', whatsapp_endpoint_id: endpointId } : null
  }
  return null
}

const draftKeyForRead = (draft: ReplyDraftRead): string | null => {
  if (draft.channel === 'email' && draft.email_thread_id != null) return emailDraftKey(draft.email_thread_id)
  if (draft.channel === 'whatsapp' && draft.whatsapp_endpoint_id != null) return whatsappDraftKey(draft.whatsapp_endpoint_id)
  return null
}

const draftAttachmentLocalKey = (draftId: number, attachmentId: number, index: number) => `draft-${draftId}-attachment-${attachmentId}-${index}`

type EmailTemplateOption = {
  id: number
  name: string
  subject: string | null
  body: string
}

type GmailDraft = {
  draft_id: string | null
  subject: string
  body_text: string
  body_html?: string | null
  body_format?: ComposerBodyFormat
}

type AiTemplateOption = {
  id: number
  name: string
}

type TenantAiSettings = {
  planner_mode?: 'off' | 'manual' | 'auto-draft' | 'auto-send'
  tenant_id: number
  available_template_ids: number[]
  default_email_template_id: number | null
  default_whatsapp_template_id: number | null
  auto_draft_email: boolean
  auto_draft_whatsapp: boolean
  auto_send_email: boolean
  auto_send_whatsapp: boolean
}

type AiAutoDraftItem = {
  id: number
  tenant_id: number
  channel: string
  template_id: number | null
  generated_text: string
  formatted_text: string | null
  quoted_context: string | null
  status: string
  scheduled_send_at: string | null
  created_at: string
}

const buildRichReplyDraftContent = (channel: 'email' | 'whatsapp', generatedText: string, formattedText: string | null): Pick<ReplyDraftEntry, 'body' | 'body_html' | 'body_format'> => {
  const formatted = (formattedText || '').trim()
  if (channel === 'email') {
    if (formatted) {
      const safeHtml = sanitizeHtml(formatted)
      return { body: htmlToPlainText(safeHtml), body_html: safeHtml, body_format: 'email_html' }
    }
    return { body: generatedText, body_html: null, body_format: 'plain' }
  }
  if (formatted) {
    return { body: formatted, body_html: whatsappMarkupToHtml(formatted), body_format: 'whatsapp_rich' }
  }
  return { body: generatedText, body_html: null, body_format: 'plain' }
}

const buildStoredReplyDraftContent = (draft: Pick<ReplyDraftRead, 'body' | 'body_html' | 'body_format'>): Pick<ReplyDraftEntry, 'body' | 'body_html' | 'body_format'> => ({
  body: draft.body ?? '',
  body_html: draft.body_html ?? null,
  body_format: draft.body_format ?? 'plain',
})

const renderFormattedDraftHtml = (channel: 'email' | 'whatsapp', formattedText: string) =>
  channel === 'email' ? sanitizeHtml(formattedText) : whatsappMarkupToHtml(formattedText)

export default function ThreadView({ tenantId, reloadSignal, onReady, onTenantLoaded, initialThreadTarget, onInitialThreadTargetConsumed }: ThreadViewProps) {
  const token = useAuthStore((state) => state.token)
  const user = useAuthStore((state) => state.user)
  const [downloadingAttachmentId, setDownloadingAttachmentId] = useState<string | null>(null)
  const downloadAttachment = useCallback(
    async (messageId: number, attachment: Attachment) => {
      const { attachment_id: attachmentId, filename } = attachment
      setDownloadingAttachmentId(attachmentId)
      try {
        const downloadUrl =
          attachment.source === 'stored'
            ? `${API_BASE_URL}/api/communications/tenants/${tenantId}/attachments/${attachment.id}/download`
            : `${API_BASE_URL}/api/integrations/gmail/messages/${messageId}/attachments/${attachmentId}`
        const response = await fetch(downloadUrl, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        })
        if (!response.ok) {
          return
        }
        const blob = await response.blob()
        const objectUrl = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = objectUrl
        link.download = filename
        link.click()
        URL.revokeObjectURL(objectUrl)
      } finally {
        setDownloadingAttachmentId((current) => (current === attachmentId ? null : current))
      }
    },
    [token, tenantId],
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
  const [showFirstMessageModal, setShowFirstMessageModal] = useState(false)
  const [showEmailLinkModal, setShowEmailLinkModal] = useState(false)
  const [emailSyncToast, setEmailSyncToast] = useState<EmailSyncToast | null>(null)
  const emailSyncToastKeyRef = useRef(0)
  const [replyTarget, setReplyTarget] = useState<ReplyTarget>(null)
  const [replyDrafts, setReplyDrafts] = useState<Record<string, ReplyDraftEntry>>({})
  const [replySending, setReplySending] = useState(false)
  const [replyCc, setReplyCc] = useState('')
  // Keyed by the same draft scope key as reply bodies, so attachments picked for one thread
  // never leak into another thread's or tenant's composer.
  const [replyAttachments, setReplyAttachments] = useState<Record<string, PendingAttachment[]>>({})
  const [aiTemplates, setAiTemplates] = useState<AiTemplateOption[]>([])
  const [tenantAiSettings, setTenantAiSettings] = useState<TenantAiSettings | null>(null)
  const [selectedAiTemplateId, setSelectedAiTemplateId] = useState('')
  const [aiDraftGenerating, setAiDraftGenerating] = useState(false)
  const [plannerRunning, setPlannerRunning] = useState(false)
  const [plannerNotice, setPlannerNotice] = useState('')
  const [aiDraftError, setAiDraftError] = useState('')
  const [plannerDraftId, setPlannerDraftId] = useState<number | null>(null)
  const [pendingAutoDrafts, setPendingAutoDrafts] = useState<AiAutoDraftItem[]>([])
  const [redoOpenDraftId, setRedoOpenDraftId] = useState<number | null>(null)
  const [redoWhat, setRedoWhat] = useState('')
  const [redoWhy, setRedoWhy] = useState('')
  const [redoSubmitting, setRedoSubmitting] = useState(false)
  const [plannerRedoOpen, setPlannerRedoOpen] = useState(false)
  const [plannerRedoWhat, setPlannerRedoWhat] = useState('')
  const [plannerRedoWhy, setPlannerRedoWhy] = useState('')
  const [plannerRedoSubmitting, setPlannerRedoSubmitting] = useState(false)
  const [selectedEmailThread, setSelectedEmailThread] = useState<EmailThreadItem | null>(null)
  const [threadTargetNotFound, setThreadTargetNotFound] = useState(false)
  const [emailNavIndex, setEmailNavIndex] = useState(0)
  const [whatsappGroupNavIndex, setWhatsappGroupNavIndex] = useState(0)
  const [whatsappBlockNavIndex, setWhatsappBlockNavIndex] = useState(0)
  const [forwardTarget, setForwardTarget] = useState<ForwardTarget>(null)
  const [forwardSubject, setForwardSubject] = useState('')
  const [forwardCc, setForwardCc] = useState('')
  const [forwardBody, setForwardBody] = useState('')
  const [forwardSending, setForwardSending] = useState(false)
  const [forwardToEmail, setForwardToEmail] = useState<string | null>(null)
  const [forwardAttachments, setForwardAttachments] = useState<PendingAttachment[]>([])
  // Encoded "{conversation_message_id}:{gmail_attachment_id}"; pre-selected when the forward
  // composer opens, and auto-unticked past the size cap.
  const [forwardOriginalIds, setForwardOriginalIds] = useState<string[]>([])
  const [emailTemplates, setEmailTemplates] = useState<EmailTemplateOption[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [templateLoading, setTemplateLoading] = useState(false)
  const [draftResults, setDraftResults] = useState<GmailDraft[] | null>(null)
  const [draftChecking, setDraftChecking] = useState(false)
  const [draftError, setDraftError] = useState('')
  const emailThreadDrag = useDraggablePosition()
  const whatsappGroupDrag = useDraggablePosition()
  const emailBackdropMouseDownRef = useRef(false)
  const whatsappBlockBackdropMouseDownRef = useRef(false)
  const whatsappGroupBackdropMouseDownRef = useRef(false)

  const emailThreadSize = useResizableSize({
    boxType: 'email-thread',
    defaultWidth: 800,
    defaultHeight: window.innerHeight * 0.85,
    minWidth: 320,
    minHeight: 400,
    maxWidth: window.innerWidth * 0.95,
    maxHeight: window.innerHeight * 0.95,
    user,
  })

  const whatsappGroupSize = useResizableSize({
    boxType: 'whatsapp-group',
    defaultWidth: 800,
    defaultHeight: window.innerHeight * 0.85,
    minWidth: 320,
    minHeight: 400,
    maxWidth: window.innerWidth * 0.95,
    maxHeight: window.innerHeight * 0.95,
    user,
  })

  const whatsappBlockSize = useResizableSize({
    boxType: 'whatsapp-block',
    defaultWidth: 500,
    defaultHeight: window.innerHeight * 0.85,
    minWidth: 320,
    minHeight: 400,
    maxWidth: window.innerWidth * 0.95,
    maxHeight: window.innerHeight * 0.95,
    user,
  })

  const selectedWhatsappEndpoint = whatsappEndpoints.find((endpoint) => String(endpoint.id) === selectedWhatsappEndpointId) ?? null
  const hasWhatsappEndpoints = whatsappEndpoints.length > 0
  const [livePollSignal, setLivePollSignal] = useState(0)

  const currentDraftKey = draftKeyForTarget(replyTarget, selectedWhatsappEndpointId)
  const currentDraft = (currentDraftKey ? replyDrafts[currentDraftKey] : null) ?? EMPTY_REPLY_DRAFT
  const replyMessage = currentDraft.body
  const replyBodyHtml = currentDraft.body_html
  const replyBodyFormat = currentDraft.body_format
  const replySubject = currentDraft.subject
  const hasReplyBodyContent = hasComposerContent(replyMessage, replyBodyHtml)
  const currentReplyAttachments = (currentDraftKey ? replyAttachments[currentDraftKey] : null) ?? EMPTY_ATTACHMENTS
  const currentReplyAttachmentIds = currentReplyAttachments
    .map((item) => item.id)
    .filter((id): id is number => id !== null)
  const plannerReplyThreadId = replyTarget && 'threadId' in replyTarget ? replyTarget.threadId : null
  const plannerReplyGroupId = replyTarget && 'groupId' in replyTarget ? replyTarget.groupId : null
  const setCurrentReplyAttachments = useCallback(
    (next: PendingAttachment[]) => {
      if (!currentDraftKey) return
      setReplyAttachments((current) => ({ ...current, [currentDraftKey]: next }))
      setReplyDrafts((current) => ({
        ...current,
        [currentDraftKey]: {
          ...(current[currentDraftKey] ?? EMPTY_REPLY_DRAFT),
          attachment_ids: next.map((item) => item.id).filter((id): id is number => id !== null),
        },
      }))
    },
    [currentDraftKey],
  )

  // Only Gmail-sourced attachments can be re-fetched from the original thread; stored blobs
  // are already re-attachable through the picker's history browser.
  const forwardableOriginalAttachments = (selectedEmailThread?.messages ?? []).flatMap((message) =>
    (message.attachments ?? [])
      .filter((attachment) => attachment.source !== 'stored')
      .map((attachment) => ({
        key: `${message.id}:${attachment.attachment_id}`,
        filename: attachment.filename,
        size: attachment.size,
      })),
  )
  const forwardOriginalsSelectedBytes = forwardableOriginalAttachments
    .filter((item) => forwardOriginalIds.includes(item.key))
    .reduce((total, item) => total + (item.size ?? 0), 0)
  const forwardOriginalsOverCap =
    forwardOriginalsSelectedBytes + forwardAttachments.reduce((total, item) => total + item.size, 0) >
    MAX_EMAIL_TOTAL_BYTES

  // Writes go through an explicit key so a caller that changes replyTarget and the body in the
  // same tick (e.g. useDraftAsReply) writes to the new scope, not the one being navigated away from.
  const writeReplyDraft = useCallback((key: string | null, patch: Partial<ReplyDraftEntry>) => {
    if (!key) return
    setReplyDrafts((current) => ({ ...current, [key]: { ...(current[key] ?? EMPTY_REPLY_DRAFT), ...patch } }))
  }, [])
  const setReplyMessage = useCallback(
    (body: string) => writeReplyDraft(currentDraftKey, { body, body_html: null, body_format: 'plain' }),
    [writeReplyDraft, currentDraftKey],
  )
  const setReplyComposerValue = useCallback(
    (value: Pick<ReplyDraftEntry, 'body' | 'body_html' | 'body_format'>) => writeReplyDraft(currentDraftKey, value),
    [writeReplyDraft, currentDraftKey],
  )
  const handleReplyComposerChange = useCallback(
    (value: { body: string; bodyHtml: string | null; bodyFormat: ComposerBodyFormat }) =>
      setReplyComposerValue({ body: value.body, body_html: value.bodyHtml, body_format: value.bodyFormat }),
    [setReplyComposerValue],
  )
  const setReplySubject = useCallback(
    (subject: string) => writeReplyDraft(currentDraftKey, { subject }),
    [writeReplyDraft, currentDraftKey],
  )

  // Mirrors of the live values so the beforeunload/tenant-switch flush never reads a stale closure.
  const replyDraftsRef = useRef<Record<string, ReplyDraftEntry>>({})
  replyDraftsRef.current = replyDrafts
  // key -> last value the server acknowledged, so a hydrated draft is not immediately re-sent.
  const persistedDraftsRef = useRef<Record<string, string>>({})
  const draftTenantIdRef = useRef<number | null>(null)
  const previousTenantIdRef = useRef<number | null | undefined>(undefined)
  // Tenant whose drafts are actually in state. Tracked separately from previousTenantIdRef so an
  // aborted first load retries hydration on the next pass instead of leaving the boxes empty.
  const hydratedDraftTenantIdRef = useRef<number | null>(null)

  const persistReplyDraft = useCallback(
    (draftTenantId: number, key: string, entry: ReplyDraftEntry, keepalive: boolean) => {
      const scope = replyDraftScopeParams(key)
      if (!scope) return
      persistedDraftsRef.current[key] = serializeReplyDraft(entry)
      fetch(`${API_BASE_URL}/api/communications/tenants/${draftTenantId}/reply-drafts`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ ...scope, subject: entry.subject || null, body: entry.body, body_html: entry.body_html, body_format: entry.body_format, attachment_ids: entry.attachment_ids }),
        keepalive,
      }).catch(() => {
        // Best-effort: drop the acknowledgement so the next debounce tick retries.
        delete persistedDraftsRef.current[key]
      })
    },
    [token],
  )

  const deleteReplyDraft = useCallback(
    (draftTenantId: number, key: string) => {
      const scope = replyDraftScopeParams(key)
      if (!scope) return
      persistedDraftsRef.current[key] = serializeReplyDraft(EMPTY_REPLY_DRAFT)
      const params = new URLSearchParams({ channel: scope.channel })
      if (scope.email_thread_id != null) params.set('email_thread_id', String(scope.email_thread_id))
      if (scope.whatsapp_endpoint_id != null) params.set('whatsapp_endpoint_id', String(scope.whatsapp_endpoint_id))
      fetch(`${API_BASE_URL}/api/communications/tenants/${draftTenantId}/reply-drafts?${params.toString()}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      }).catch(() => {})
    },
    [token],
  )

  // Pushes every scope whose text has drifted from the server copy. Used for the debounced
  // autosave and for the last-chance flush on tenant switch / page unload.
  const flushReplyDrafts = useCallback(
    (keepalive: boolean) => {
      const draftTenantId = draftTenantIdRef.current
      if (!draftTenantId) return
      Object.entries(replyDraftsRef.current).forEach(([key, entry]) => {
        if (serializeReplyDraft(entry) === persistedDraftsRef.current[key]) return
        persistReplyDraft(draftTenantId, key, entry, keepalive)
      })
    },
    [persistReplyDraft],
  )

  useEffect(() => {
    const timeoutId = window.setTimeout(() => flushReplyDrafts(false), REPLY_DRAFT_AUTOSAVE_DELAY_MS)
    return () => window.clearTimeout(timeoutId)
  }, [replyDrafts, replyAttachments, flushReplyDrafts])

  useEffect(() => {
    const handleBeforeUnload = () => flushReplyDrafts(true)
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
      flushReplyDrafts(true)
    }
  }, [flushReplyDrafts])

  // A WhatsApp draft typed before an account was chosen is transient; once an account is picked
  // it becomes a real, persistable draft for that linked chat.
  useEffect(() => {
    if (!selectedWhatsappEndpointId) return
    setReplyDrafts((current) => {
      const pending = current[WHATSAPP_PENDING_DRAFT_KEY]
      if (!pending || (!pending.body && !pending.subject)) return current
      const { [WHATSAPP_PENDING_DRAFT_KEY]: _pending, ...rest } = current
      return { ...rest, [whatsappDraftKey(selectedWhatsappEndpointId)]: pending }
    })
  }, [selectedWhatsappEndpointId])

  // Color/label are resolved from the fixed WHATSAPP_ACCOUNT_DIRECTORY (by account identity),
  // not from per-tenant link order, so SSI is always green and EDI is always violet everywhere.
  const getWhatsappAccountPalette = (accountKey: string) => {
    const known = WHATSAPP_ACCOUNT_DIRECTORY[accountKey]
    if (known) return WHATSAPP_ACCOUNT_PALETTES[known.paletteIndex]
    // Unrecognized account: still deterministic per key, but drawn from the remaining palette
    // entries so it never collides with the reserved SSI/EDI colors.
    const fallbackPalettes = WHATSAPP_ACCOUNT_PALETTES.slice(2)
    let hash = 0
    for (let i = 0; i < accountKey.length; i += 1) hash = (hash * 31 + accountKey.charCodeAt(i)) >>> 0
    return fallbackPalettes[hash % fallbackPalettes.length]
  }

  const getWhatsappAccountLabel = (accountKey: string) => {
    const known = WHATSAPP_ACCOUNT_DIRECTORY[accountKey]
    if (known) return known.label
    return accountKey === 'unknown' ? 'Unknown account' : accountKey
  }

  // Account color/label alone can't distinguish two chats linked on the same account (e.g. two
  // different phone numbers on the same WhatsApp business number), so when that account has more
  // than one active linked chat, surface which specific chat a message belongs to as extra badge
  // text -- only when needed, so the common single-chat-per-account case stays uncluttered.
  const getWhatsappMessageChatLabel = (message: WhatsappTimelineMessage) => {
    const messageAccountId = (message.external_account_id || '').trim().toLowerCase()
    if (!messageAccountId) return null
    const accountLinks = whatsappLinks.filter((link) => link.is_active && (link.external_account_id || '').trim().toLowerCase() === messageAccountId)
    if (accountLinks.length < 2) return null
    const messageChatId = (message.external_chat_namespace || message.whatsapp_chat_id || '').trim().toLowerCase()
    if (!messageChatId) return null
    const matchedLink = accountLinks.find((link) => (link.chat_id || '').trim().toLowerCase() === messageChatId)
    if (!matchedLink) return null
    return matchedLink.chat_display_name?.trim() || matchedLink.chat_id
  }

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
    if (!token) return
    let cancelled = false
    const loadForwardSetup = async () => {
      const [templatesResponse, adminSettingsResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/email-templates`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_BASE_URL}/api/admin-settings`, { headers: { Authorization: `Bearer ${token}` } }),
      ])
      if (cancelled) return
      if (templatesResponse.ok) setEmailTemplates(await templatesResponse.json())
      if (adminSettingsResponse.ok) {
        const data = await adminSettingsResponse.json()
        setForwardToEmail(data.forward_to_email ?? null)
      }
    }
    loadForwardSetup()
    return () => {
      cancelled = true
    }
  }, [token])

  useEffect(() => {
    if (!token) return
    let cancelled = false
    const loadAiTemplates = async () => {
      const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates`, { headers: { Authorization: `Bearer ${token}` } })
      if (cancelled || !response.ok) return
      setAiTemplates(await response.json())
    }
    loadAiTemplates()
    return () => {
      cancelled = true
    }
  }, [token])

  useEffect(() => {
    if (!tenantId || !token) {
      setTenantAiSettings(null)
      return
    }
    let cancelled = false
    const loadTenantAiSettings = async () => {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/ai-settings`, { headers: { Authorization: `Bearer ${token}` } })
      if (cancelled || !response.ok) return
      setTenantAiSettings(await response.json())
    }
    loadTenantAiSettings()
    return () => {
      cancelled = true
    }
  }, [tenantId, token])

  // Preselect the tenant's default AI template for whichever channel the reply box is
  // currently open for, so "Draft with AI" works with zero clicks beyond typing a rough draft.
  useEffect(() => {
    if (!replyTarget || !tenantAiSettings) return
    const defaultId = replyTarget.type === 'email' ? tenantAiSettings.default_email_template_id : tenantAiSettings.default_whatsapp_template_id
    setSelectedAiTemplateId(defaultId ? String(defaultId) : '')
    setAiDraftError('')
  }, [replyTarget, tenantAiSettings])


  useEffect(() => {
    setPlannerDraftId(null)
    setPlannerRedoOpen(false)
    setPlannerRedoWhat('')
    setPlannerRedoWhy('')
  }, [tenantId, replyTarget?.type, plannerReplyThreadId, plannerReplyGroupId])

  const loadPendingAutoDrafts = useCallback(async () => {
    if (!tenantId || !token) {
      setPendingAutoDrafts([])
      return
    }
    const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts?tenant_id=${tenantId}`, { headers: { Authorization: `Bearer ${token}` } })
    if (!response.ok) return
    setPendingAutoDrafts(await response.json())
  }, [tenantId, token])

  useEffect(() => {
    loadPendingAutoDrafts()
  }, [loadPendingAutoDrafts, livePollSignal])

  const pendingAutoDraftForChannel = (channel: 'email' | 'whatsapp') =>
    pendingAutoDrafts.find((draft) => draft.channel === channel) ?? null

  const useAutoDraft = async (draft: AiAutoDraftItem) => {
    setReplyComposerValue(buildRichReplyDraftContent(draft.channel === 'email' ? 'email' : 'whatsapp', draft.generated_text, draft.formatted_text))
    await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/mark-used`, {
      method: 'PUT',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    await loadPendingAutoDrafts()
  }

  const dismissAutoDraft = async (draft: AiAutoDraftItem) => {
    await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/dismiss`, {
      method: 'PUT',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    await loadPendingAutoDrafts()
  }

  const cancelAutoSend = async (draft: AiAutoDraftItem) => {
    await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/cancel-auto-send`, {
      method: 'PUT',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    await loadPendingAutoDrafts()
  }

  const submitRedo = async (draft: AiAutoDraftItem) => {
    const what = redoWhat.trim()
    if (!what || redoSubmitting) return
    try {
      setRedoSubmitting(true)
      const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${draft.id}/redo`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ what, why: redoWhy.trim() || null }),
      })
      if (response.ok) {
        setRedoOpenDraftId(null)
        setRedoWhat('')
        setRedoWhy('')
      }
      await loadPendingAutoDrafts()
    } finally {
      setRedoSubmitting(false)
    }
  }

  const renderPendingAutoDraftBanner = (channel: 'email' | 'whatsapp') => {
    const draft = pendingAutoDraftForChannel(channel)
    if (!draft) return null
    const draftText = (draft.formatted_text || draft.generated_text || '').trim()
    return (
      <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-2">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-700">
          {draft.status === 'pending_auto_send' ? 'AI draft - sending automatically soon' : 'Pending AI draft'}
        </p>
        {draft.formatted_text ? (
          <div
            className="mt-1.5 max-h-28 overflow-y-auto break-words text-sm leading-5 text-gray-700"
            dangerouslySetInnerHTML={{ __html: renderFormattedDraftHtml(channel, draft.formatted_text) }}
          />
        ) : (
          <p className="mt-1.5 max-h-28 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-5 text-gray-700">{draftText}</p>
        )}
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => useAutoDraft(draft)}
            className="rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-indigo-700"
          >
            Use this draft
          </button>
          {draft.status === 'pending_auto_send' ? (
            <button
              type="button"
              onClick={() => cancelAutoSend(draft)}
              className="rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50"
            >
              Cancel auto-send
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => {
              setRedoOpenDraftId((current) => (current === draft.id ? null : draft.id))
              setRedoWhat('')
              setRedoWhy('')
            }}
            className="rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50"
          >
            Redo
          </button>
          <button
            type="button"
            onClick={() => dismissAutoDraft(draft)}
            className="rounded-lg px-2.5 py-1 text-xs font-semibold text-gray-500 hover:bg-gray-50 hover:text-rose-600"
          >
            Dismiss
          </button>
        </div>
        {redoOpenDraftId === draft.id ? (
          <div className="mt-1.5 space-y-1.5 rounded-lg border border-gray-200 bg-white p-1.5">
            <input
              type="text"
              value={redoWhat}
              onChange={(event) => setRedoWhat(event.target.value)}
              placeholder="What to change (required)"
              className="w-full rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-900 outline-none focus:border-cyan-300"
            />
            <input
              type="text"
              value={redoWhy}
              onChange={(event) => setRedoWhy(event.target.value)}
              placeholder="Why (optional)"
              className="w-full rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-900 outline-none focus:border-cyan-300"
            />
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={() => submitRedo(draft)}
                disabled={!redoWhat.trim() || redoSubmitting}
                className="rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="inline-flex items-center gap-1.5">
                  {redoSubmitting ? <InlineSpinner className="h-3 w-3" /> : null}
                  {redoSubmitting ? 'Redoing...' : 'Submit redo'}
                </span>
              </button>
              <button
                type="button"
                onClick={() => setRedoOpenDraftId(null)}
                className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}
      </div>
    )
  }

  const renderPlannerRedoButton = () => {
    if (!plannerEnabled) return null
    return (
      <button
        type="button"
        onClick={() => {
          setPlannerRedoOpen((current) => !current)
          setPlannerRedoWhat('')
          setPlannerRedoWhy('')
        }}
        disabled={plannerRunning || !plannerDraftId}
        title={plannerDraftId ? 'Re-run the planner with an explicit change note' : 'Run the planner once before redoing it'}
        className="rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Redo
      </button>
    )
  }

  const renderPlannerRedoForm = () => {
    if (!plannerRedoOpen) return null
    return (
      <div className="space-y-1.5 rounded-lg border border-gray-200 bg-gray-50 p-1.5">
        <input
          type="text"
          value={plannerRedoWhat}
          onChange={(event) => setPlannerRedoWhat(event.target.value)}
          placeholder="What to change (required)"
          className="w-full rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 outline-none focus:border-cyan-300"
        />
        <input
          type="text"
          value={plannerRedoWhy}
          onChange={(event) => setPlannerRedoWhy(event.target.value)}
          placeholder="Why (optional)"
          className="w-full rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-900 outline-none focus:border-cyan-300"
        />
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={handlePlannerRedo}
            disabled={!plannerRedoWhat.trim() || plannerRedoSubmitting}
            className="rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="inline-flex items-center gap-1.5">
              {plannerRedoSubmitting ? <InlineSpinner className="h-3 w-3" /> : null}
              {plannerRedoSubmitting ? 'Redoing...' : 'Submit redo'}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setPlannerRedoOpen(false)}
            className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-600 hover:bg-white"
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  const aiTemplateOptions = tenantAiSettings && tenantAiSettings.available_template_ids.length
    ? aiTemplates.filter((template) => tenantAiSettings.available_template_ids.includes(template.id))
    : aiTemplates

  const handleGenerateAiDraft = async () => {
    if (!tenantId || !replyTarget || aiDraftGenerating) return
    try {
      setAiDraftGenerating(true)
      setAiDraftError('')
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/ai-draft`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          channel: replyTarget.type,
          template_id: selectedAiTemplateId ? Number(selectedAiTemplateId) : null,
          rough_draft: replyMessage.trim() || null,
        }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || 'Failed to generate AI draft')
      }
      const data: { generated_text: string; formatted_text: string | null; template_id: number } = await response.json()
      setReplyComposerValue(buildRichReplyDraftContent(replyTarget.type, data.generated_text, data.formatted_text))
      setSelectedAiTemplateId(String(data.template_id))
    } catch (err) {
      setAiDraftError(err instanceof Error ? err.message : 'Failed to generate AI draft')
    } finally {
      setAiDraftGenerating(false)
    }
  }

  const plannerEnabled = (tenantAiSettings?.planner_mode ?? 'off') !== 'off'

  const handleRunPlanner = async () => {
    if (!tenantId || !replyTarget || plannerRunning) return
    try {
      setPlannerRunning(true)
      setAiDraftError('')
      setPlannerNotice('')
      setPlannerDraftId(null)
      setPlannerRedoOpen(false)
      setPlannerRedoWhat('')
      setPlannerRedoWhy('')
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/ai-plan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          channel: replyTarget.type,
          ...(replyTarget.type === 'email' ? { email_thread_id: replyTarget.threadId } : {}),
          ...(replyTarget.type === 'whatsapp' && selectedWhatsappEndpointId
            ? { whatsapp_endpoint_id: Number(selectedWhatsappEndpointId) }
            : {}),
          // Whatever is already in the box is the operator's intent, so it leads the plan.
          rough_draft: replyMessage.trim() || null,
          attachment_ids: currentReplyAttachmentIds,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(data?.detail || 'Failed to run the planner')
      }
      setPlannerDraftId(data?.draft_id ?? null)
      setPlannerNotice('Planner running - check AI Drafts.')
    } catch (err) {
      setAiDraftError(err instanceof Error ? err.message : 'Failed to run the planner')
    } finally {
      setPlannerRunning(false)
    }
  }

  const handlePlannerRedo = async () => {
    const what = plannerRedoWhat.trim()
    if (!tenantId || !replyTarget || !what || plannerRedoSubmitting || !plannerDraftId) return
    try {
      setPlannerRedoSubmitting(true)
      setAiDraftError('')
      setPlannerNotice('')
      const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts/${plannerDraftId}/redo`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          what,
          why: plannerRedoWhy.trim() || null,
        }),
      })
      const data = (await response.json().catch(() => null)) as (AiAutoDraftItem & { detail?: string }) | null
      if (!response.ok) {
        throw new Error(data?.detail || 'Failed to redo the planner draft')
      }
      if (!data) {
        throw new Error('Failed to redo the planner draft')
      }
      setPlannerDraftId(data.id)
      setReplyComposerValue(buildRichReplyDraftContent(replyTarget.type, data.generated_text, data.formatted_text))
      if (data.template_id != null) setSelectedAiTemplateId(String(data.template_id))
      if (data.status === 'needs_review') {
        setPlannerNotice('The reviewer never approved this draft - read it carefully before sending.')
      }
      setPlannerRedoOpen(false)
      setPlannerRedoWhat('')
      setPlannerRedoWhy('')
    } catch (err) {
      setAiDraftError(err instanceof Error ? err.message : 'Failed to redo the planner draft')
    } finally {
      setPlannerRedoSubmitting(false)
    }
  }

  const handlePreviewAiPayload = () => {
    if (!tenantId || !replyTarget) return
    const previewId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    window.localStorage.setItem(
      `ai-payload-preview:${previewId}`,
      JSON.stringify({
        tenantId,
        channel: replyTarget.type,
        templateId: selectedAiTemplateId ? Number(selectedAiTemplateId) : null,
        roughDraft: replyMessage.trim() || null,
      }),
    )
    window.open(`/ai-payload-preview?id=${previewId}`, '_blank')
  }

  useEffect(() => {
    // Only a genuine tenant change resets the open scope. This effect also reruns on
    // reloadSignal/livePollSignal, and those must not wipe a reply that is being typed.
    const tenantChanged = previousTenantIdRef.current !== tenantId
    if (tenantChanged) {
      // Push whatever is unsaved for the outgoing tenant before dropping it from state.
      flushReplyDrafts(true)
      previousTenantIdRef.current = tenantId
      draftTenantIdRef.current = tenantId ?? null
      persistedDraftsRef.current = {}
      hydratedDraftTenantIdRef.current = null
      setReplyDrafts({})
      setReplyAttachments({})
      setReplyTarget(null)
      setReplyCc('')
      setForwardTarget(null)
      setForwardCc('')
      setForwardBody('')
      setForwardSubject('')
      setSelectedEmailThread(null)
      setSelectedWhatsappGroup(null)
      setSelectedWhatsappBlock(null)
      setDraftResults(null)
      setDraftError('')
    }

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

    if (tenantChanged) {
      // Auto-resync every linked WhatsApp chat for this tenant on page open, throttled
      // server-side per chat so re-opening the same tenant shortly after doesn't re-fire it.
      // Fires alongside the fetches below rather than blocking them; refreshes the grouped
      // thread once it resolves so anything backfilled shows up without a manual refresh.
      fetch(`${API_BASE_URL}/api/threads/${tenantId}/whatsapp-links/resync-all`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
        .then((response) => (response.ok ? loadGroupedThread() : undefined))
        .catch(() => {})
    }

    const controller = new AbortController()
    const activeTenantId = tenantId

    const loadThread = async () => {
      try {
        setLoading(true)
        setError('')
        const [tenantResponse, threadResponse, endpointResponse, linksResponse, replyDraftsResponse] = await Promise.all([
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
          fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/reply-drafts`, {
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
        onTenantLoaded?.(tenantData.name)
        setItems(groupedThreadData.items)
        setWhatsappEndpoints(endpointData)

        if (initialThreadTarget) {
          setThreadTargetNotFound(false)
          if (initialThreadTarget.channel === 'email') {
            const target = groupedThreadData.items.find(
              (item): item is EmailThreadItem => item.type === 'email_thread' && String(item.thread_id) === initialThreadTarget.threadRef,
            )
            if (target) openEmailThread(target)
            else setThreadTargetNotFound(true)
          } else if (initialThreadTarget.channel === 'whatsapp') {
            const target = groupedThreadData.items.find(
              (item): item is WhatsappGroupItem =>
                item.type === 'whatsapp_group' && item.messages.some((message) => String(message.id) === initialThreadTarget.threadRef),
            )
            if (target) openWhatsappGroup(target)
            else setThreadTargetNotFound(true)
          }
          onInitialThreadTargetConsumed?.()
        }
        setSelectedWhatsappEndpointId((current) => {
          if (current && endpointData.some((endpoint) => String(endpoint.id) === current)) {
            return current
          }
          if (endpointData.length === 1) return String(endpointData[0].id)
          const mostRecentInbound = endpointData.find((endpoint) => endpoint.is_most_recent_inbound)
          return mostRecentInbound ? String(mostRecentInbound.id) : ''
        })
        if (linksResponse.ok) {
          const linksData: ThreadWhatsappLink[] = await linksResponse.json()
          setWhatsappLinks(Array.isArray(linksData) ? linksData : [])
        }
        // Hydrate once per tenant only: a background refresh must not clobber text the user is
        // typing right now with the last value the server happened to have.
        if (hydratedDraftTenantIdRef.current !== activeTenantId && replyDraftsResponse.ok) {
          const draftData: ReplyDraftRead[] = await replyDraftsResponse.json()
          const hydratedDrafts: Record<string, ReplyDraftEntry> = {}
          const hydratedAttachments: Record<string, PendingAttachment[]> = {}
          const acknowledged: Record<string, string> = {}
          ;(Array.isArray(draftData) ? draftData : []).forEach((draft) => {
            const key = draftKeyForRead(draft)
            if (!key) return
            const attachments = (Array.isArray(draft.attachments) ? draft.attachments : []).map((attachment, index) => ({
              localKey: draftAttachmentLocalKey(draft.id, attachment.id, index),
              id: attachment.id,
              filename: attachment.filename,
              size: attachment.size_bytes,
              progress: 100,
            }))
            const attachmentIds = attachments.length
              ? attachments.map((attachment) => attachment.id).filter((id): id is number => id !== null)
              : (Array.isArray(draft.attachment_ids) ? draft.attachment_ids : []).filter((id): id is number => id !== null)
            const entry = { subject: draft.subject ?? '', ...buildStoredReplyDraftContent(draft), attachment_ids: attachmentIds }
            hydratedDrafts[key] = entry
            hydratedAttachments[key] = attachments
            acknowledged[key] = serializeReplyDraft(entry)
          })
          persistedDraftsRef.current = acknowledged
          hydratedDraftTenantIdRef.current = activeTenantId
          setReplyDrafts(hydratedDrafts)
          setReplyAttachments(hydratedAttachments)
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load thread')
      } finally {
        // `finally` runs even after the catch's early return on abort. When this load was
        // superseded (tenant switched), skip these side effects so we don't flip loading state or
        // fire onReady for a stale tenant and race the newly started load.
        if (!controller.signal.aborted) {
          setLoading(false)
          onReady?.(activeTenantId)
        }
      }
    }

    loadThread()
    return () => controller.abort()
    // openEmailThread/openWhatsappGroup/onInitialThreadTargetConsumed are stable-enough per
    // render and intentionally excluded to avoid re-running this fetch on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, token, reloadSignal, livePollSignal, initialThreadTarget])

  const navigateMessage = (kind: 'email' | 'whatsapp_group' | 'whatsapp_block', direction: 1 | -1) => {
    if (kind === 'email' && selectedEmailThread) {
      const total = buildThreadTimelineEntries(selectedEmailThread).length
      const next = Math.max(0, Math.min(emailNavIndex + direction, total - 1))
      setEmailNavIndex(next)
      scrollToMessageIndex('[data-email-messages]', next)
    } else if (kind === 'whatsapp_group' && selectedWhatsappGroup) {
      const total = selectedWhatsappGroup.messages.length
      const next = Math.max(0, Math.min(whatsappGroupNavIndex + direction, total - 1))
      setWhatsappGroupNavIndex(next)
      scrollToMessageIndex('[data-whatsapp-messages]', next)
    } else if (kind === 'whatsapp_block' && selectedWhatsappBlock) {
      const total = selectedWhatsappBlock.messages.length
      const next = Math.max(0, Math.min(whatsappBlockNavIndex + direction, total - 1))
      setWhatsappBlockNavIndex(next)
      scrollToMessageIndex('[data-whatsapp-block-messages]', next)
    }
  }

  useEffect(() => {
    if (!selectedWhatsappGroup && !selectedEmailThread) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSelectedWhatsappGroup(null)
        setSelectedEmailThread(null)
        return
      }
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
      // Reply/forward text areas also use arrow keys for cursor movement, so
      // jump-navigation must yield to any focused editable element.
      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return

      event.preventDefault()
      const direction = event.key === 'ArrowUp' ? -1 : 1
      if (selectedWhatsappBlock) {
        navigateMessage('whatsapp_block', direction)
      } else if (selectedEmailThread) {
        navigateMessage('email', direction)
      } else if (selectedWhatsappGroup) {
        navigateMessage('whatsapp_group', direction)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedWhatsappGroup, selectedEmailThread, selectedWhatsappBlock, emailNavIndex, whatsappGroupNavIndex, whatsappBlockNavIndex])

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
    if (selectedEmailThread) {
      const total = buildThreadTimelineEntries(selectedEmailThread).length
      setEmailNavIndex(total ? total - 1 : 0)
    }
    if (selectedWhatsappGroup) {
      const total = selectedWhatsappGroup.messages.length
      setWhatsappGroupNavIndex(total ? total - 1 : 0)
    }
  }, [selectedWhatsappGroup, selectedEmailThread, replyTarget?.type])

  useEffect(() => {
    if (!selectedWhatsappBlock) return
    const total = selectedWhatsappBlock.messages.length
    setWhatsappBlockNavIndex(total ? total - 1 : 0)
    const scrollContainer = document.querySelector('[data-whatsapp-block-messages]')
    if (scrollContainer) {
      setTimeout(() => {
        scrollContainer.scrollTop = scrollContainer.scrollHeight
      }, 0)
    }
  }, [selectedWhatsappBlock])

  // Keeps the MessageJumpNav counter synced to the topmost visible message
  // while the user scrolls manually (not just on click/keyboard nav).
  useEffect(() => {
    if (!selectedEmailThread) return
    const container = document.querySelector<HTMLElement>('[data-email-messages]')
    if (!container) return
    const items = Array.from(container.querySelectorAll<HTMLElement>('[data-message-index]'))
    if (!items.length) return

    // IntersectionObserver callbacks only report entries whose state just
    // changed, not every currently-visible item, so the visible set must be
    // tracked cumulatively across callbacks rather than recomputed each time.
    const visible = new Set<number>()
    let currentTop = -1
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const index = Number((entry.target as HTMLElement).dataset.messageIndex)
          if (Number.isNaN(index)) return
          if (entry.isIntersecting) visible.add(index)
          else visible.delete(index)
        })
        if (!visible.size) return
        const topmost = Math.min(...visible)
        if (topmost !== currentTop) {
          currentTop = topmost
          setEmailNavIndex(topmost)
        }
      },
      { root: container, threshold: [0, 0.1] },
    )
    items.forEach((item) => observer.observe(item))
    return () => observer.disconnect()
  }, [selectedEmailThread])

  useEffect(() => {
    if (!selectedWhatsappBlock) return
    const container = document.querySelector<HTMLElement>('[data-whatsapp-block-messages]')
    if (!container) return
    const items = Array.from(container.querySelectorAll<HTMLElement>('[data-message-index]'))
    if (!items.length) return

    const visible = new Set<number>()
    let currentTop = -1
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const index = Number((entry.target as HTMLElement).dataset.messageIndex)
          if (Number.isNaN(index)) return
          if (entry.isIntersecting) visible.add(index)
          else visible.delete(index)
        })
        if (!visible.size) return
        const topmost = Math.min(...visible)
        if (topmost !== currentTop) {
          currentTop = topmost
          setWhatsappBlockNavIndex(topmost)
        }
      },
      { root: container, threshold: [0, 0.1] },
    )
    items.forEach((item) => observer.observe(item))
    return () => observer.disconnect()
  }, [selectedWhatsappBlock])

  useEffect(() => {
    if (!selectedWhatsappGroup) return
    const container = document.querySelector<HTMLElement>('[data-whatsapp-messages]')
    if (!container) return
    const items = Array.from(container.querySelectorAll<HTMLElement>('[data-message-index]'))
    if (!items.length) return

    const visible = new Set<number>()
    let currentTop = -1
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const index = Number((entry.target as HTMLElement).dataset.messageIndex)
          if (Number.isNaN(index)) return
          if (entry.isIntersecting) visible.add(index)
          else visible.delete(index)
        })
        if (!visible.size) return
        const topmost = Math.min(...visible)
        if (topmost !== currentTop) {
          currentTop = topmost
          setWhatsappGroupNavIndex(topmost)
        }
      },
      { root: container, threshold: [0, 0.1] },
    )
    items.forEach((item) => observer.observe(item))
    return () => observer.disconnect()
  }, [selectedWhatsappGroup])

  const openWhatsappGroup = (group: WhatsappGroupItem) => {
    setSelectedWhatsappGroup(group)
    setReplyTarget({ type: 'whatsapp', groupId: group.group_id })
  }

  const openEmailThread = (thread: EmailThreadItem) => {
    setSelectedEmailThread((current) => {
      if (!current || current.thread_id !== thread.thread_id) {
        setDraftResults(null)
        setDraftError('')
      }
      return thread
    })
    setReplyTarget({ type: 'email', threadId: thread.thread_id, providerThreadId: thread.provider_thread_id, providerAccountId: thread.provider_account_id || 0, subject: thread.subject })
    setReplyCc('')
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

  const reloadWhatsappEndpoints = async () => {
    if (!tenantId) return
    const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/whatsapp-endpoints`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!response.ok) return
    const data: WhatsappEndpointOption[] = await response.json()
    setWhatsappEndpoints(Array.isArray(data) ? data : [])
  }

  const handleFirstWhatsappMessageSent = async () => {
    // Unlike a normal reply, this creates a brand-new TenantChannelEndpoint, so the reply
    // compose account dropdown (whatsappEndpoints) needs refreshing too, not just the links
    // list and the message thread.
    await reloadWhatsappLinks()
    await reloadWhatsappEndpoints()
    await loadGroupedThread()
  }

  const handleEmailSyncStarted = (jobId: string, email: string) => {
    emailSyncToastKeyRef.current += 1
    setEmailSyncToast({ jobId, email, status: 'running' })
  }

  useEffect(() => {
    if (!emailSyncToast || emailSyncToast.status !== 'running') return
    let cancelled = false
    const pollOnce = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/integrations/gmail/accounts/sync-status/${emailSyncToast.jobId}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!response.ok) return
        const job = await response.json()
        if (cancelled || job.status === 'running') return
        emailSyncToastKeyRef.current += 1
        if (job.status === 'done') {
          setEmailSyncToast((current) => (current?.jobId === emailSyncToast.jobId ? { ...current, status: 'done', result: job.result } : current))
          await loadGroupedThread()
        } else {
          setEmailSyncToast((current) => (current?.jobId === emailSyncToast.jobId ? { ...current, status: 'error', error: job.error } : current))
        }
      } catch {
        // Transient poll failure -- the interval below will retry.
      }
    }
    const intervalId = window.setInterval(pollOnce, 1500)
    pollOnce()
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emailSyncToast?.jobId, emailSyncToast?.status, token])

  useEffect(() => {
    if (!emailSyncToast || emailSyncToast.status === 'running') return
    const timeoutId = window.setTimeout(() => setEmailSyncToast(null), 8000)
    return () => window.clearTimeout(timeoutId)
  }, [emailSyncToast])

  const handleSendReply = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    // An attachment-only message is allowed, so an empty body alone no longer blocks the send.
    if (!tenantId || replySending || !replyTarget) return
    if (!hasReplyBodyContent && currentReplyAttachmentIds.length === 0) return
    if (currentReplyAttachments.some((item) => item.error || item.id === null)) {
      setError('Wait for attachments to finish uploading, or remove the failed ones.')
      return
    }

    try {
      setReplySending(true)
      setError('')

      if (replyTarget.type === 'email') {
        const requestBody = {
          channel: 'email',
          subject: replySubject.trim() || replyTarget.subject || '',
          cc: replyCc.trim() || undefined,
          message: replyMessage,
          message_format: replyBodyFormat,
          body_html: replyBodyHtml,
          email_thread_id: replyTarget.threadId,
          attachment_ids: currentReplyAttachmentIds,
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
          message_format: replyBodyFormat,
          body_html: replyBodyHtml,
          whatsapp_endpoint_id: Number(selectedWhatsappEndpointId),
          external_account_id: selectedWhatsappEndpoint?.external_account_id ?? null,
          attachment_ids: currentReplyAttachmentIds,
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
      // Drop the draft for the scope that was just sent - locally and on the server - so it does
      // not come back on the next load. Other scopes' drafts are untouched.
      if (currentDraftKey) {
        setReplyDrafts((current) => {
          const { [currentDraftKey]: _sent, ...rest } = current
          return rest
        })
        setReplyAttachments((current) => {
          const { [currentDraftKey]: _sentAttachments, ...rest } = current
          return rest
        })
        deleteReplyDraft(tenantId, currentDraftKey)
      }
      if (replyTarget.type === 'whatsapp') {
        setSelectedWhatsappGroup(null)
        setSelectedWhatsappBlock(null)
      }
      setReplyTarget(null)
      setReplyCc('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message')
    } finally {
      setReplySending(false)
    }
  }

  const openForwardPanel = (thread: EmailThreadItem) => {
    openEmailThread(thread)
    setForwardTarget({ threadId: thread.thread_id, providerThreadId: thread.provider_thread_id, subject: thread.subject })
    setForwardCc('')
    setForwardSubject(thread.subject ? (thread.subject.toLowerCase().startsWith('fwd:') ? thread.subject : `Fwd: ${thread.subject}`) : 'Fwd:')
    setForwardBody('')
    setForwardAttachments([])
    // Pre-select the thread's own attachments, then drop the tail that would push the message
    // past the email cap - carrying everything is the common case, but a long thread can hold
    // far more than one message can.
    let runningBytes = 0
    setForwardOriginalIds(
      (thread.messages ?? []).flatMap((message) =>
        (message.attachments ?? [])
          .filter((attachment) => attachment.source !== 'stored')
          .filter((attachment) => {
            runningBytes += attachment.size ?? 0
            return runningBytes <= MAX_EMAIL_TOTAL_BYTES
          })
          .map((attachment) => `${message.id}:${attachment.attachment_id}`),
      ),
    )
    setSelectedTemplateId('')
    setDraftResults(null)
    setDraftError('')
  }

  const handleSelectTemplate = async (templateId: string) => {
    setSelectedTemplateId(templateId)
    if (!templateId || !tenantId) return
    try {
      setTemplateLoading(true)
      const response = await fetch(`${API_BASE_URL}/api/email-templates/${templateId}/preview`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ tenant_id: tenantId }),
      })
      if (!response.ok) return
      const data = await response.json()
      setForwardBody(data.body ?? '')
      if (data.subject) setForwardSubject(data.subject)
    } finally {
      setTemplateLoading(false)
    }
  }

  const handleSendForward = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!tenantId || !forwardTarget || !forwardBody.trim() || forwardSending) return
    if (forwardAttachments.some((item) => item.error || item.id === null)) {
      setError('Wait for attachments to finish uploading, or remove the failed ones.')
      return
    }

    try {
      setForwardSending(true)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/forward`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          email_thread_id: forwardTarget.threadId,
          subject: forwardSubject.trim() || forwardTarget.subject || '',
          cc: forwardCc.trim() || undefined,
          body: forwardBody,
          attachment_ids: forwardAttachments
            .map((item) => item.id)
            .filter((id): id is number => id !== null),
          include_original_attachment_ids: forwardOriginalIds,
        }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || 'Failed to forward email')
      }

      await loadGroupedThread()
      setForwardTarget(null)
      setForwardCc('')
      setForwardBody('')
      setForwardSubject('')
      setForwardAttachments([])
      setForwardOriginalIds([])
      setSelectedTemplateId('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to forward email')
    } finally {
      setForwardSending(false)
    }
  }

  const checkForAiDraft = async (thread: EmailThreadItem) => {
    if (!tenantId) return
    try {
      setDraftChecking(true)
      setDraftError('')
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/threads/${thread.thread_id}/draft`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || 'Failed to check for AI draft')
      }
      const data = await response.json()
      setDraftResults(Array.isArray(data) ? data : [])
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : 'Failed to check for AI draft')
      setDraftResults(null)
    } finally {
      setDraftChecking(false)
    }
  }

  const useDraftAsReply = (draft: GmailDraft, thread: EmailThreadItem) => {
    setReplyTarget({ type: 'email', threadId: thread.thread_id, providerThreadId: thread.provider_thread_id, providerAccountId: thread.provider_account_id || 0, subject: thread.subject })
    setReplyCc('')
    // Keyed on the thread being opened, not on the current replyTarget, which is still the
    // previously open scope until this render commits.
    writeReplyDraft(emailDraftKey(thread.thread_id), { subject: draft.subject || '', ...buildStoredReplyDraftContent({ body: draft.body_text || '', body_html: draft.body_html ?? null, body_format: draft.body_format ?? 'plain' }) })
    setForwardTarget(null)
    setDraftResults(null)
  }

  return (
    <div className="flex h-full min-h-0 min-h-[680px] flex-col">
      <div className="border-b border-gray-200 px-4 py-3">
        <div className="flex flex-col gap-3 xl:grid xl:grid-cols-[minmax(0,1fr)_minmax(22rem,34rem)_auto] xl:items-center xl:gap-4">
          <div className="min-w-0">
            <h2 className="truncate text-xl font-semibold text-gray-900">{tenant ? tenant.name : 'Messages'}</h2>
            <p className="mt-1 truncate text-sm text-gray-500">
              {tenant ? [tenant.email || 'No email on file', tenant.phone || 'No phone on file'].join(' Â· ') : 'Select a tenant'}
            </p>
          </div>
          {tenantId ? <TenantBrainQuickChat tenantId={tenantId} /> : null}
          {tenantId ? (
            <div className="flex flex-wrap items-center justify-end gap-2 xl:justify-self-end">
              <button
                type="button"
                onClick={() => setShowFirstMessageModal(true)}
                className="rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700"
              >
                New WhatsApp
              </button>
              <button
                type="button"
                onClick={() => setShowLinkChatModal(true)}
                className="rounded-xl border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-gray-700 transition hover:bg-gray-50"
              >
                {whatsappLinks.some((link) => link.is_active) ? 'Manage chats' : 'Link chat'}
              </button>
              <button
                type="button"
                onClick={() => setShowEmailLinkModal(true)}
                className="rounded-xl border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-gray-700 transition hover:bg-gray-50"
              >
                Manage emails
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {emailSyncToast ? (
        <ToastStack>
          <ToastCard toastKey={emailSyncToastKeyRef.current} tone={emailSyncToast.status === 'error' ? 'error' : emailSyncToast.status === 'done' ? 'success' : 'info'} durationMs={8000}>
            {emailSyncToast.status === 'running' ? (
              <p className="font-medium">Syncing Gmail history for {emailSyncToast.email}...</p>
            ) : emailSyncToast.status === 'done' ? (
              <>
                <p className="font-semibold">Gmail sync complete</p>
                <p className="mt-1">
                  {emailSyncToast.result?.conversations_matched ?? 0} conversation
                  {emailSyncToast.result?.conversations_matched === 1 ? '' : 's'} matched for {emailSyncToast.email} across{' '}
                  {emailSyncToast.result?.accounts_checked ?? 0} account{emailSyncToast.result?.accounts_checked === 1 ? '' : 's'}.
                </p>
                {emailSyncToast.result?.accounts_failed ? (
                  <p className="mt-1 text-xs text-emerald-800/80">{emailSyncToast.result.accounts_failed} account(s) failed to sync.</p>
                ) : null}
              </>
            ) : (
              <p className="font-semibold">Gmail sync for {emailSyncToast.email} failed{emailSyncToast.error ? `: ${emailSyncToast.error}` : ''}</p>
            )}
          </ToastCard>
        </ToastStack>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 [scrollbar-width:thin] [scrollbar-color:rgba(6,182,212,0.35)_transparent]">
        {loading ? <p className="text-sm text-gray-500">Loading tenant thread...</p> : null}
        {replySending ? <p className="mt-1 text-sm text-gray-500">Sending message...</p> : null}
        {error ? <p className="mb-4 text-sm text-rose-500">{error}</p> : null}
        {threadTargetNotFound ? (
          <div className="mb-4 flex items-start justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            <span>The original thread for that notification is no longer available. Showing the tenant's full timeline instead.</span>
            <button
              type="button"
              onClick={() => setThreadTargetNotFound(false)}
              className="shrink-0 text-amber-600 transition hover:text-amber-900"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        ) : null}

        <div className="space-y-4">
          {items.map((item, itemIndex) => {
            // Mount-only stagger: the CSS animation plays once when a card first
            // mounts (thread load, tenant switch, or a newly-arrived item) and does
            // not replay on live-poll re-renders that keep the same keys.
            const entryDelayMs = Math.min(itemIndex, 8) * 40
            if (item.type === 'email_thread') {
              const latestMessage = item.messages[item.messages.length - 1]
              return (
                <article
                  key={item.thread_id}
                  className="animate-slide-up rounded-2xl border border-gray-200 bg-gray-50"
                  style={{ animationDelay: `${entryDelayMs}ms` }}
                >
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
                        {formatMailboxAndTenantEmailLabel(item.provider_account_display_name || item.provider_account_email, item.matched_tenant_email)}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-gray-600 shadow-sm">
                        {item.messages.length} messages
                      </span>
                      <div className="flex gap-2">
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
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            openForwardPanel(item)
                          }}
                          className="rounded-lg border border-cyan-300 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 hover:bg-cyan-100"
                        >
                          Draft with AI
                        </button>
                      </div>
                    </div>
                  </div>
                </article>
              )
            }

            const firstMessage = item.messages[0]
            const lastMessage = item.messages[item.messages.length - 1]
            return (
              <article
                key={item.group_id}
                className="animate-slide-up rounded-2xl border border-emerald-200 bg-emerald-50"
                style={{ animationDelay: `${entryDelayMs}ms` }}
              >
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
          className="fixed inset-0 z-50 flex items-center justify-center gap-4 px-4"
          onMouseDown={(event) => {
            emailBackdropMouseDownRef.current = event.target === event.currentTarget
          }}
          onClick={() => {
            if (!emailBackdropMouseDownRef.current) return
            emailBackdropMouseDownRef.current = false
            setSelectedEmailThread(null)
            setSelectedWhatsappBlock(null)
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="email-thread-modal-title"
            className="relative flex flex-col rounded-2xl border border-gray-200 bg-white shadow-sm"
            style={{ ...emailThreadDrag.style, ...emailThreadSize.style }}
            onClick={(event) => event.stopPropagation()}
          >
            <div
              className="flex shrink-0 cursor-move items-center justify-between gap-3 border-b border-gray-200 px-3 py-2"
              onPointerDown={emailThreadDrag.handlePointerDown}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="shrink-0 rounded-full bg-cyan-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-700">
                    Email
                  </span>
                  <h3 id="email-thread-modal-title" className="truncate text-sm font-semibold text-gray-900">
                    {selectedEmailThread.subject || 'Untitled conversation'}
                  </h3>
                </div>
                <p className="mt-0.5 truncate text-[11px] text-gray-500">
                  {selectedEmailThread.messages.length === 1 ? '1 message' : `${selectedEmailThread.messages.length} messages`}
                  {' · '}
                  {formatMailboxAndTenantEmailLabel(
                    selectedEmailThread.provider_account_display_name || selectedEmailThread.provider_account_email,
                    selectedEmailThread.matched_tenant_email,
                  )}
                  {' · '}
                  {formatTimestamp(selectedEmailThread.anchor_timestamp || selectedEmailThread.messages[0]?.sent_at || selectedEmailThread.messages[selectedEmailThread.messages.length - 1]?.sent_at || new Date().toISOString())}
                </p>
              </div>
              <button
                type="button"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => setSelectedEmailThread(null)}
                className="shrink-0 rounded-xl px-2.5 py-1.5 text-xs font-semibold text-gray-500 hover:bg-gray-100 hover:text-gray-900"
              >
                Close
              </button>
            </div>

            <div className="relative min-h-0 flex-1">
            <div className="absolute inset-0 overflow-y-auto px-3 py-2" data-email-messages>
              <div className="space-y-1.5 mb-2">
                {buildThreadTimelineEntries(selectedEmailThread).map((entry, entryIndex) => {
                  if (entry.kind === 'email') {
                    const messageItem = entry.message
                    const isOutbound = messageItem.direction === 'outbound'
                    return (
                      <article
                        key={`email-${messageItem.id}`}
                        data-message-index={entryIndex}
                        className={`max-w-[92%] rounded-2xl border px-2.5 py-1.5 ${isOutbound ? 'ml-auto border-cyan-200 bg-cyan-50' : 'border-amber-200 bg-amber-50'}`}
                      >
                        <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-gray-500">
                          <span className={`rounded-full px-2 py-1 font-semibold ${isOutbound ? 'bg-cyan-100 text-cyan-700' : 'bg-amber-100 text-amber-700'}`}>
                            {isOutbound ? 'Outbound' : 'Inbound'}
                          </span>
                          {messageItem.ai_generated ? <AiGeneratedBadge /> : null}
                          <span>{formatTimestamp(messageItem.sent_at)}</span>
                        </div>
                        {messageItem.subject ? <p className="mt-1 text-sm font-semibold text-gray-900">{messageItem.subject}</p> : null}
                        {(messageItem.sender_email || messageItem.recipient_email || messageItem.cc) ? (
                          <p className="mt-1 text-xs text-gray-500">
                            {messageItem.sender_email ? <span>From: {messageItem.sender_email}</span> : null}
                            {messageItem.sender_email && messageItem.recipient_email ? <span> · </span> : null}
                            {messageItem.recipient_email ? <span>To: {messageItem.recipient_email}</span> : null}
                            {(messageItem.sender_email || messageItem.recipient_email) && messageItem.cc ? <span> · </span> : null}
                            {messageItem.cc ? <span>Cc: {messageItem.cc}</span> : null}
                          </p>
                        ) : null}
                        {renderMessageBody(messageItem) ? (
                          <div
                            className="prose prose-sm max-w-none mt-1 overflow-x-auto text-sm leading-5 text-gray-700 prose-p:my-2 prose-a:text-cyan-700 prose-a:underline prose-blockquote:border-gray-300 prose-blockquote:pl-4 prose-blockquote:text-gray-600"
                            dangerouslySetInnerHTML={renderMessageBody(messageItem)}
                          />
                        ) : (
                          <p className="mt-1 whitespace-pre-wrap text-sm leading-5 text-gray-700">{messageItem.body_text || messageItem.body_display || messageItem.body}</p>
                        )}
                        <AttachmentChips
                          messageId={messageItem.id}
                          attachments={messageItem.attachments}
                          downloadingAttachmentId={downloadingAttachmentId}
                          onDownload={downloadAttachment}
                        />
                      </article>
                    )
                  }

                  const block = entry.block
                  const lastBlockMessage = block.messages[block.messages.length - 1]
                  return (
                    <article key={`whatsapp-block-${block.block_id}`} data-message-index={entryIndex} className="rounded-2xl border border-emerald-200 bg-emerald-50">
                      <div
                        onClick={() => {
                          setSelectedWhatsappBlock({ ...block, threadId: selectedEmailThread.thread_id })
                          setReplyTarget({ type: 'whatsapp', groupId: block.block_id })
                        }}
                        className="flex w-full cursor-pointer items-start justify-between gap-4 px-3 py-2 text-left transition hover:bg-emerald-100/70"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-emerald-700">
                            <span className="rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-800">WhatsApp</span>
                            <span>{formatTimestamp(block.end_at || lastBlockMessage?.created_at || new Date().toISOString())}</span>
                          </div>
                          <p className="mt-1.5 truncate text-sm font-semibold text-gray-900">
                            {block.message_count === 1 ? 'WhatsApp message' : `WhatsApp messages (${block.message_count})`}
                          </p>
                          <p className="mt-0.5 truncate text-sm text-gray-600">{lastBlockMessage ? extractWhatsappPreviewText(lastBlockMessage) : 'No preview available'}</p>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1.5">
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
                            className="rounded-lg border border-emerald-300 bg-white px-2.5 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-50"
                          >
                            Reply
                          </button>
                        </div>
                      </div>
                    </article>
                  )
                })}
              </div>

              {!replyTarget && !forwardTarget ? (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => openForwardPanel(selectedEmailThread)}
                    className="rounded-lg border border-cyan-300 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 hover:bg-cyan-100"
                  >
                    Draft with AI
                  </button>
                  <button
                    type="button"
                    disabled={draftChecking}
                    onClick={() => checkForAiDraft(selectedEmailThread)}
                    className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {draftChecking ? 'Checking...' : 'Check for AI draft'}
                  </button>
                </div>
              ) : null}

              {draftError ? <p className="text-sm text-rose-500">{draftError}</p> : null}

              {draftResults ? (
                draftResults.length ? (
                  <div className="space-y-2">
                    {draftResults.map((draft, index) => (
                      <div key={draft.draft_id ?? index} className="rounded-xl border border-amber-200 bg-amber-50 p-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">AI Draft</p>
                        {draft.subject ? <p className="mt-1.5 text-sm font-semibold text-gray-900">{draft.subject}</p> : null}
                        {draft.body_html ? (
                          <div
                            className="mt-1.5 max-h-28 overflow-y-auto break-words text-sm leading-5 text-gray-700"
                            dangerouslySetInnerHTML={{ __html: sanitizeHtml(draft.body_html) }}
                          />
                        ) : (
                          <p className="mt-1.5 max-h-28 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-5 text-gray-700">{draft.body_text}</p>
                        )}
                        <button
                          type="button"
                          onClick={() => useDraftAsReply(draft, selectedEmailThread)}
                          className="mt-2 rounded-lg bg-amber-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-amber-700"
                        >
                          Use this draft
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">No AI draft found yet for this thread.</p>
                )
              ) : null}

              {forwardTarget && forwardTarget.threadId === selectedEmailThread.thread_id ? (
                <form onSubmit={handleSendForward} className="space-y-3 rounded-xl border border-cyan-200 bg-cyan-50 p-4">
                  <p className="text-xs text-gray-500">
                    Sends this thread to {forwardToEmail || 'the configured AI address (set it in Admin Settings)'}.
                  </p>
                  {emailTemplates.length ? (
                    <div className="space-y-2">
                      <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="modal-forward-template">
                        Template
                      </label>
                      <select
                        id="modal-forward-template"
                        value={selectedTemplateId}
                        onChange={(event) => handleSelectTemplate(event.target.value)}
                        disabled={templateLoading}
                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                      >
                        <option value="">No template</option>
                        {emailTemplates.map((template) => (
                          <option key={template.id} value={template.id}>{template.name}</option>
                        ))}
                      </select>
                    </div>
                  ) : null}
                  <div className="space-y-2">
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="modal-forward-subject">
                      Subject
                    </label>
                    <input
                      id="modal-forward-subject"
                      value={forwardSubject}
                      onChange={(event) => setForwardSubject(event.target.value)}
                      placeholder="Subject"
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="modal-forward-cc">
                      Cc
                    </label>
                    <input
                      id="modal-forward-cc"
                      value={forwardCc}
                      onChange={(event) => setForwardCc(event.target.value)}
                      placeholder="team@example.com"
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                    />
                  </div>
                  <textarea
                    value={forwardBody}
                    onChange={(event) => setForwardBody(event.target.value)}
                    rows={5}
                    placeholder="Write a note or pick a template above..."
                    disabled={forwardSending || templateLoading}
                    className="w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
                  />
                  <p className="text-xs text-gray-500">The full thread history is included automatically below this text when sent.</p>
                  {forwardableOriginalAttachments.length > 0 ? (
                    <div className="space-y-1 rounded-lg border border-slate-200 bg-white/60 p-2">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
                        Attachments from this thread
                      </p>
                      {forwardableOriginalAttachments.map((item) => (
                        <label key={item.key} className="flex items-center gap-2 text-xs text-gray-700">
                          <input
                            type="checkbox"
                            checked={forwardOriginalIds.includes(item.key)}
                            onChange={(event) => {
                              setForwardOriginalIds((current) =>
                                event.target.checked
                                  ? [...current, item.key]
                                  : current.filter((existing) => existing !== item.key),
                              )
                            }}
                          />
                          <span className="truncate">📎 {item.filename}</span>
                          {item.size ? <span className="text-gray-400">{formatBytes(item.size)}</span> : null}
                        </label>
                      ))}
                      {forwardOriginalsOverCap ? (
                        <p className="text-xs text-amber-600">
                          Selected attachments exceed the {formatBytes(MAX_EMAIL_TOTAL_BYTES)} email limit — the
                          server will omit the overflow and note it in the message.
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                  {tenantId ? (
                    <AttachmentPicker
                      tenantId={tenantId}
                      token={token}
                      channel="email"
                      attachments={forwardAttachments}
                      onChange={setForwardAttachments}
                      disabled={forwardSending}
                    />
                  ) : null}
                  <div className="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setForwardTarget(null)}
                      className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={forwardSending || !forwardBody.trim()}
                      className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {forwardSending ? 'Sending...' : 'Send to AI'}
                    </button>
                  </div>
                </form>
              ) : null}
            </div>
            <MessageJumpNav
              total={buildThreadTimelineEntries(selectedEmailThread).length}
              currentIndex={emailNavIndex}
              onPrev={() => navigateMessage('email', -1)}
              onNext={() => navigateMessage('email', 1)}
            />
            </div>

            <div className="shrink-0 border-t border-gray-200 px-3 py-2">
              {replyTarget?.type === 'email' && replyTarget.threadId === selectedEmailThread.thread_id ? (
                <form onSubmit={handleSendReply} className="space-y-2 rounded-xl border border-cyan-200 bg-cyan-50 p-2.5">
                  <div className="space-y-1">
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="modal-email-subject">
                      Subject
                    </label>
                    <input
                      id="modal-email-subject"
                      value={replySubject}
                      onChange={(event) => setReplySubject(event.target.value)}
                      placeholder={replyTarget.subject || 'Subject'}
                      className="w-full rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="modal-email-cc">
                      Cc
                    </label>
                    <input
                      id="modal-email-cc"
                      value={replyCc}
                      onChange={(event) => setReplyCc(event.target.value)}
                      placeholder="team@example.com"
                      className="w-full rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
                    />
                  </div>
                  {renderPendingAutoDraftBanner('email')}
                  <AiDraftControls
                    tenantId={tenantId}
                    channel={replyTarget.type}
                    message={replyMessage}
                    selectedTemplateId={selectedAiTemplateId}
                    onSelectedTemplateIdChange={setSelectedAiTemplateId}
                    templates={aiTemplateOptions}
                    aiDraftGenerating={aiDraftGenerating}
                    plannerEnabled={plannerEnabled}
                    plannerRunning={plannerRunning}
                    onGenerateAiDraft={handleGenerateAiDraft}
                    onRunPlanner={handleRunPlanner}
                    onPreviewAiPayload={handlePreviewAiPayload}
                    plannerRedoButton={renderPlannerRedoButton()}
                  />
                  {aiDraftError ? <p className="text-xs text-rose-500">{aiDraftError}</p> : null}
                  {plannerNotice ? <p className="text-xs text-amber-600">{plannerNotice}</p> : null}
                  {renderPlannerRedoForm()}
                  <RichMessageComposer
                    channel="email"
                    value={{ body: replyMessage, bodyHtml: replyBodyHtml, bodyFormat: replyBodyFormat }}
                    onChange={handleReplyComposerChange}
                    placeholder="Write your reply..."
                    disabled={replySending}
                  />
                  {tenantId ? (
                    <AttachmentPicker
                      tenantId={tenantId}
                      token={token}
                      channel="email"
                      attachments={currentReplyAttachments}
                      onChange={setCurrentReplyAttachments}
                      disabled={replySending}
                    />
                  ) : null}
                  <div className="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setReplyTarget(null)}
                      className="rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={replySending || (!hasReplyBodyContent && currentReplyAttachmentIds.length === 0)}
                      className="rounded-lg bg-cyan-600 px-2.5 py-1 text-xs font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {replySending ? 'Sending...' : 'Send'}
                    </button>
                  </div>
                </form>
              ) : (
                <button
                  type="button"
                  onClick={() => setReplyTarget({ type: 'email', threadId: selectedEmailThread.thread_id, providerThreadId: selectedEmailThread.provider_thread_id, providerAccountId: selectedEmailThread.provider_account_id || 0, subject: selectedEmailThread.subject })}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50"
                >
                  Reply
                </button>
              )}
            </div>

            <div
              className="absolute bottom-1 right-1 cursor-nwse-resize p-2 text-gray-400 hover:text-gray-600"
              onPointerDown={emailThreadSize.handlePointerDown}
              onClick={(e) => e.stopPropagation()}
              title="Drag to resize"
            >
              <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M14.414 2.586a2 2 0 00-2.828 0l-9 9a2 2 0 102.828 2.828l9-9a2 2 0 000-2.828zM16.586 15.586l-1.414 1.414a2 2 0 11-2.828-2.828l1.414-1.414a2 2 0 112.828 2.828z" clipRule="evenodd" />
              </svg>
            </div>
          </div>

          {selectedWhatsappBlock && selectedWhatsappBlock.threadId === selectedEmailThread.thread_id ? (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center px-4"
              onMouseDown={(event) => {
                whatsappBlockBackdropMouseDownRef.current = event.target === event.currentTarget
              }}
              onClick={() => {
                if (!whatsappBlockBackdropMouseDownRef.current) return
                whatsappBlockBackdropMouseDownRef.current = false
                setSelectedWhatsappBlock(null)
              }}
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="whatsapp-block-panel-title"
                className="relative flex flex-col rounded-2xl border border-gray-200 bg-white shadow-sm"
                style={whatsappBlockSize.style}
                onClick={(event) => event.stopPropagation()}
              >
              <div className="flex shrink-0 items-center justify-between gap-3 border-b border-gray-200 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-700">
                      WhatsApp
                    </span>
                    <h3 id="whatsapp-block-panel-title" className="truncate text-sm font-semibold text-gray-900">
                      {tenant?.name || 'WhatsApp conversation'}
                    </h3>
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-gray-500">
                    {selectedWhatsappBlock.message_count === 1 ? '1 message' : `${selectedWhatsappBlock.message_count} messages`}
                    {' · '}
                    {formatTimestamp(selectedWhatsappBlock.start_at || selectedWhatsappBlock.messages[0]?.created_at || new Date().toISOString())}
                    {selectedWhatsappBlock.end_at ? ` - ${formatTimestamp(selectedWhatsappBlock.end_at)}` : ''}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedWhatsappBlock(null)}
                  className="shrink-0 rounded-xl px-2.5 py-1.5 text-xs font-semibold text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                >
                  Close
                </button>
              </div>

              <div className="relative min-h-0 flex-1">
              <div className="absolute inset-0 overflow-y-auto px-3 py-2" data-whatsapp-block-messages>
                <div className="space-y-1.5 mb-2">
                  {selectedWhatsappBlock.messages.map((blockMessage, blockMessageIndex) => {
                    const isOutbound = blockMessage.direction === 'outbound'
                    const accountKey = getWhatsappMessageAccountKey(blockMessage)
                    const palette = getWhatsappAccountPalette(accountKey)
                    return (
                      <article
                        key={blockMessage.id}
                        data-message-index={blockMessageIndex}
                        className={`max-w-[92%] rounded-2xl border px-2.5 py-1.5 ${isOutbound ? palette.outboundBubble : palette.inboundBubble}`}
                      >
                        <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-gray-500">
                          <span
                            title={accountKey}
                            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 font-semibold ${isOutbound ? palette.outboundBadge : palette.inboundBadge}`}
                          >
                            <span className={`h-2 w-2 rounded-full ${palette.dot}`} />
                            {isOutbound ? 'Outbound' : 'Inbound'} · {getWhatsappAccountLabel(accountKey)}
                            {getWhatsappMessageChatLabel(blockMessage) ? ` · ${getWhatsappMessageChatLabel(blockMessage)}` : ''}
                          </span>
                          {blockMessage.ai_generated ? <AiGeneratedBadge /> : null}
                          <span>{formatTimestamp(blockMessage.created_at)}</span>
                        </div>
                        {blockMessage.subject ? <p className="mt-1 text-sm font-semibold text-gray-900">{blockMessage.subject}</p> : null}
                        <div
                        className="prose prose-sm mt-1 max-w-none text-sm leading-5 text-gray-700 prose-p:my-1 prose-pre:my-2"
                        dangerouslySetInnerHTML={{ __html: whatsappMarkupToHtml(blockMessage.message) }}
                      />
                        <AttachmentChips
                          messageId={blockMessage.id}
                          attachments={blockMessage.attachments}
                          downloadingAttachmentId={downloadingAttachmentId}
                          onDownload={downloadAttachment}
                        />
                      </article>
                    )
                  })}
                </div>

              </div>
              <MessageJumpNav
                total={selectedWhatsappBlock.messages.length}
                currentIndex={whatsappBlockNavIndex}
                onPrev={() => navigateMessage('whatsapp_block', -1)}
                onNext={() => navigateMessage('whatsapp_block', 1)}
              />
              </div>

              <div className="shrink-0 border-t border-gray-200 px-3 py-2">
                {replyTarget?.type === 'whatsapp' && replyTarget.groupId === selectedWhatsappBlock.block_id ? (
                  <form onSubmit={handleSendReply} className="space-y-2 rounded-xl border border-cyan-200 bg-cyan-50 p-2.5">
                    <div className="space-y-1">
                      <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="block-whatsapp-endpoint">
                        WhatsApp account
                      </label>
                      <select
                        id="block-whatsapp-endpoint"
                        value={selectedWhatsappEndpointId}
                        onChange={(event) => setSelectedWhatsappEndpointId(event.target.value)}
                        disabled={replySending || !hasWhatsappEndpoints}
                        className="w-full rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
                      >
                        <option value="">{hasWhatsappEndpoints ? 'Choose an account' : 'No active WhatsApp accounts'}</option>
                        {whatsappEndpoints.map((endpoint) => (
                          <option key={endpoint.id} value={endpoint.id}>
                            {formatWhatsappEndpointLabel(endpoint)}
                          </option>
                        ))}
                      </select>
                    </div>
                    {renderPendingAutoDraftBanner('whatsapp')}
                  <AiDraftControls
                    tenantId={tenantId}
                    channel={replyTarget.type}
                    message={replyMessage}
                    selectedTemplateId={selectedAiTemplateId}
                    onSelectedTemplateIdChange={setSelectedAiTemplateId}
                    templates={aiTemplateOptions}
                    aiDraftGenerating={aiDraftGenerating}
                    plannerEnabled={plannerEnabled}
                    plannerRunning={plannerRunning}
                    onGenerateAiDraft={handleGenerateAiDraft}
                    onRunPlanner={handleRunPlanner}
                    onPreviewAiPayload={handlePreviewAiPayload}
                    plannerRedoButton={renderPlannerRedoButton()}
                  />
                  {aiDraftError ? <p className="text-xs text-rose-500">{aiDraftError}</p> : null}
                    {plannerNotice ? <p className="text-xs text-amber-600">{plannerNotice}</p> : null}
                    {renderPlannerRedoForm()}
                    <RichMessageComposer
                      channel="whatsapp"
                      value={{ body: replyMessage, bodyHtml: replyBodyHtml, bodyFormat: replyBodyFormat }}
                      onChange={handleReplyComposerChange}
                      placeholder="Write your reply..."
                      disabled={replySending}
                    />
                    {tenantId ? (
                      <AttachmentPicker
                        tenantId={tenantId}
                        token={token}
                        channel="whatsapp"
                        attachments={currentReplyAttachments}
                        onChange={setCurrentReplyAttachments}
                        disabled={replySending}
                      />
                    ) : null}
                    <div className="flex items-center justify-between gap-2">
                      <button
                        type="button"
                        onClick={() => setReplyTarget(null)}
                        className="rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={replySending || (!hasReplyBodyContent && currentReplyAttachmentIds.length === 0) || !selectedWhatsappEndpointId}
                        className="rounded-lg bg-cyan-600 px-2.5 py-1 text-xs font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {replySending ? 'Sending...' : 'Send'}
                      </button>
                    </div>
                  </form>
                ) : (
                  <button
                    type="button"
                    onClick={() => setReplyTarget({ type: 'whatsapp', groupId: selectedWhatsappBlock.block_id })}
                    className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50"
                  >
                    Reply
                  </button>
                )}
              </div>

              <div
                className="absolute bottom-1 right-1 cursor-nwse-resize p-2 text-gray-400 hover:text-gray-600"
                onPointerDown={whatsappBlockSize.handlePointerDown}
                onClick={(e) => e.stopPropagation()}
                title="Drag to resize"
              >
                <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M14.414 2.586a2 2 0 00-2.828 0l-9 9a2 2 0 102.828 2.828l9-9a2 2 0 000-2.828zM16.586 15.586l-1.414 1.414a2 2 0 11-2.828-2.828l1.414-1.414a2 2 0 112.828 2.828z" clipRule="evenodd" />
                </svg>
              </div>
            </div>
          </div>
          ) : null}
        </div>
      ) : null}

      {selectedWhatsappGroup ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          onMouseDown={(event) => {
            whatsappGroupBackdropMouseDownRef.current = event.target === event.currentTarget
          }}
          onClick={() => {
            if (!whatsappGroupBackdropMouseDownRef.current) return
            whatsappGroupBackdropMouseDownRef.current = false
            setSelectedWhatsappGroup(null)
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="whatsapp-group-modal-title"
            className="relative flex flex-col rounded-2xl border border-gray-200 bg-white shadow-sm"
            style={{ ...whatsappGroupDrag.style, ...whatsappGroupSize.style }}
            onClick={(event) => event.stopPropagation()}
          >
            <div
              className="flex shrink-0 cursor-move items-center justify-between gap-3 border-b border-gray-200 px-3 py-2"
              onPointerDown={whatsappGroupDrag.handlePointerDown}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-700">
                    WhatsApp
                  </span>
                  <h3 id="whatsapp-group-modal-title" className="truncate text-sm font-semibold text-gray-900">
                    {tenant?.name || 'WhatsApp conversation'}
                  </h3>
                </div>
                <p className="mt-0.5 truncate text-[11px] text-gray-500">
                  {selectedWhatsappGroup.message_count === 1 ? '1 message' : `${selectedWhatsappGroup.message_count} messages`}
                  {' · '}
                  {selectedWhatsappGroup.start_timestamp && selectedWhatsappGroup.end_timestamp
                    ? `${formatTimestamp(selectedWhatsappGroup.start_timestamp)} - ${formatTimestamp(selectedWhatsappGroup.end_timestamp)}`
                    : formatTimestamp(selectedWhatsappGroup.start_timestamp || selectedWhatsappGroup.messages[0]?.created_at || selectedWhatsappGroup.messages[selectedWhatsappGroup.messages.length - 1]?.created_at || new Date().toISOString())}
                </p>
              </div>
              <button
                type="button"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => setSelectedWhatsappGroup(null)}
                className="shrink-0 rounded-xl px-2.5 py-1.5 text-xs font-semibold text-gray-500 hover:bg-gray-100 hover:text-gray-900"
              >
                Close
              </button>
            </div>

            <div className="relative min-h-0 flex-1">
            <div className="absolute inset-0 overflow-y-auto px-3 py-2" data-whatsapp-messages>
              <div className="space-y-1.5 mb-2">
                {selectedWhatsappGroup.messages.map((blockMessage, blockMessageIndex) => {
                  const isOutbound = blockMessage.direction === 'outbound'
                  const accountKey = getWhatsappMessageAccountKey(blockMessage)
                  const palette = getWhatsappAccountPalette(accountKey)
                  return (
                    <article
                      key={blockMessage.id}
                      data-message-index={blockMessageIndex}
                      className={`max-w-[92%] rounded-2xl border px-2.5 py-1.5 ${isOutbound ? palette.outboundBubble : palette.inboundBubble}`}
                    >
                      <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-gray-500">
                        <span
                          title={accountKey}
                          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 font-semibold ${isOutbound ? palette.outboundBadge : palette.inboundBadge}`}
                        >
                          <span className={`h-2 w-2 rounded-full ${palette.dot}`} />
                          {isOutbound ? 'Outbound' : 'Inbound'} · {getWhatsappAccountLabel(accountKey)}
                          {getWhatsappMessageChatLabel(blockMessage) ? ` · ${getWhatsappMessageChatLabel(blockMessage)}` : ''}
                        </span>
                        {blockMessage.ai_generated ? <AiGeneratedBadge /> : null}
                        <span>{formatTimestamp(blockMessage.created_at)}</span>
                      </div>
                      {blockMessage.subject ? <p className="mt-1 text-sm font-semibold text-gray-900">{blockMessage.subject}</p> : null}
                      <div
                        className="prose prose-sm mt-1 max-w-none text-sm leading-5 text-gray-700 prose-p:my-1 prose-pre:my-2"
                        dangerouslySetInnerHTML={{ __html: whatsappMarkupToHtml(blockMessage.message) }}
                      />
                      <AttachmentChips
                        messageId={blockMessage.id}
                        attachments={blockMessage.attachments}
                        downloadingAttachmentId={downloadingAttachmentId}
                        onDownload={downloadAttachment}
                      />
                    </article>
                  )
                })}
              </div>
            </div>
            <MessageJumpNav
              total={selectedWhatsappGroup.messages.length}
              currentIndex={whatsappGroupNavIndex}
              onPrev={() => navigateMessage('whatsapp_group', -1)}
              onNext={() => navigateMessage('whatsapp_group', 1)}
            />
            </div>

            <div className="shrink-0 border-t border-gray-200 px-3 py-2">
              {replyTarget?.type === 'whatsapp' && replyTarget.groupId === selectedWhatsappGroup.group_id ? (
                <form onSubmit={handleSendReply} className="space-y-2 rounded-xl border border-cyan-200 bg-cyan-50 p-2.5">
                  <div className="space-y-1">
                    <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="modal-whatsapp-endpoint">
                      WhatsApp account
                    </label>
                    <select
                      id="modal-whatsapp-endpoint"
                      value={selectedWhatsappEndpointId}
                      onChange={(event) => setSelectedWhatsappEndpointId(event.target.value)}
                      disabled={replySending || !hasWhatsappEndpoints}
                      className="w-full rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
                    >
                      <option value="">{hasWhatsappEndpoints ? 'Choose an account' : 'No active WhatsApp accounts'}</option>
                      {whatsappEndpoints.map((endpoint) => (
                        <option key={endpoint.id} value={endpoint.id}>
                          {formatWhatsappEndpointLabel(endpoint)}
                        </option>
                      ))}
                    </select>
                  </div>
                  {renderPendingAutoDraftBanner('whatsapp')}
                  <AiDraftControls
                    tenantId={tenantId}
                    channel={replyTarget.type}
                    message={replyMessage}
                    selectedTemplateId={selectedAiTemplateId}
                    onSelectedTemplateIdChange={setSelectedAiTemplateId}
                    templates={aiTemplateOptions}
                    aiDraftGenerating={aiDraftGenerating}
                    plannerEnabled={plannerEnabled}
                    plannerRunning={plannerRunning}
                    onGenerateAiDraft={handleGenerateAiDraft}
                    onRunPlanner={handleRunPlanner}
                    onPreviewAiPayload={handlePreviewAiPayload}
                    plannerRedoButton={renderPlannerRedoButton()}
                  />
                  {aiDraftError ? <p className="text-xs text-rose-500">{aiDraftError}</p> : null}
                  {plannerNotice ? <p className="text-xs text-amber-600">{plannerNotice}</p> : null}
                  {renderPlannerRedoForm()}
                  <RichMessageComposer
                    channel="whatsapp"
                    value={{ body: replyMessage, bodyHtml: replyBodyHtml, bodyFormat: replyBodyFormat }}
                    onChange={handleReplyComposerChange}
                    placeholder="Write your reply..."
                    disabled={replySending}
                  />
                  {tenantId ? (
                    <AttachmentPicker
                      tenantId={tenantId}
                      token={token}
                      channel="whatsapp"
                      attachments={currentReplyAttachments}
                      onChange={setCurrentReplyAttachments}
                      disabled={replySending}
                    />
                  ) : null}
                  <div className="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setReplyTarget(null)}
                      className="rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={replySending || (!hasReplyBodyContent && currentReplyAttachmentIds.length === 0) || !selectedWhatsappEndpointId}
                      className="rounded-lg bg-cyan-600 px-2.5 py-1 text-xs font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {replySending ? 'Sending...' : 'Send'}
                    </button>
                  </div>
                </form>
              ) : (
                <button
                  type="button"
                  onClick={() => setReplyTarget({ type: 'whatsapp', groupId: selectedWhatsappGroup.group_id })}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50"
                >
                  Reply
                </button>
              )}
            </div>

            <div
              className="absolute bottom-1 right-1 cursor-nwse-resize p-2 text-gray-400 hover:text-gray-600"
              onPointerDown={whatsappGroupSize.handlePointerDown}
              onClick={(e) => e.stopPropagation()}
              title="Drag to resize"
            >
              <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M14.414 2.586a2 2 0 00-2.828 0l-9 9a2 2 0 102.828 2.828l9-9a2 2 0 000-2.828zM16.586 15.586l-1.414 1.414a2 2 0 11-2.828-2.828l1.414-1.414a2 2 0 112.828 2.828z" clipRule="evenodd" />
              </svg>
            </div>
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

      {tenantId ? (
        <FirstWhatsAppMessageModal
          open={showFirstMessageModal}
          tenantId={tenantId}
          tenantName={tenant?.name}
          prefillPhone={tenant?.phone || tenant?.mobile || null}
          onClose={() => setShowFirstMessageModal(false)}
          onSent={handleFirstWhatsappMessageSent}
        />
      ) : null}

      {tenantId ? (
        <EmailLinkModal
          open={showEmailLinkModal}
          tenantId={tenantId}
          tenantName={tenant?.name}
          bookingId={tenant?.booking_id ?? undefined}
          onClose={() => setShowEmailLinkModal(false)}
          onChanged={loadGroupedThread}
          onSyncStarted={handleEmailSyncStarted}
        />
      ) : null}
    </div>
  )
}
