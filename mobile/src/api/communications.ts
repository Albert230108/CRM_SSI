import { apiClient } from './client'

/**
 * Communications endpoints (`backend/app/api/communications.py`, router prefix /communications,
 * mounted under /api → paths are /api/communications/...).
 *
 * The unified tenant thread comes from the "grouped-thread" endpoint, whose shapes mirror
 * `backend/app/services/thread_timeline_service.py` (MixedTimelineRead and friends). The MVP
 * renders text only — email `body_display` (quoted history already stripped server-side) and
 * WhatsApp `message` — so rich HTML rendering is deferred per the plan.
 */

// --- grouped-thread response shapes (subset used by the MVP) ---

export type TimelineMessageRead = {
  id: number
  provider: string
  provider_message_id: string
  direction: string
  sender_email: string | null
  recipient_email: string | null
  subject: string | null
  cc: string | null
  body: string
  body_text: string | null
  body_html: string | null
  attachments: unknown[]
  sent_at: string
  ai_generated: boolean
  /** Server-computed: body with quoted reply history stripped — best for display. */
  body_display: string
}

export type TimelineWhatsappMessageRead = {
  id: number
  tenant_id: number
  channel: string
  direction: string
  provider: string | null
  message: string
  provider_message_id: string | null
  created_at: string
  ai_generated: boolean
  attachments: unknown[]
}

export type TimelineWhatsappBlockRead = {
  block_id: string
  start_at: string | null
  end_at: string | null
  messages: TimelineWhatsappMessageRead[]
  message_count: number
}

export type TimelineEmailThreadRead = {
  type: 'email_thread'
  thread_id: number
  provider_thread_id: string
  provider_account_email: string | null
  provider_account_display_name: string | null
  subject: string | null
  preview_text: string | null
  anchor_timestamp: string
  messages: TimelineMessageRead[]
  whatsapp_blocks: TimelineWhatsappBlockRead[]
}

export type TimelineWhatsappGroupRead = {
  type: 'whatsapp_group'
  group_id: string
  start_timestamp: string | null
  end_timestamp: string | null
  messages: TimelineWhatsappMessageRead[]
  message_count: number
}

export type MixedTimelineItem = TimelineEmailThreadRead | TimelineWhatsappGroupRead

export type MixedTimelineRead = {
  tenant_id: number
  tenant_name: string
  items: MixedTimelineItem[]
}

// --- outbound / endpoints ---

/** Mirrors `CommunicationRead` (`backend/app/schemas/communication.py`). */
export type CommunicationRead = {
  id: number
  tenant_id: number
  channel: string
  direction: string
  message: string
  subject: string | null
  created_at: string
}

/** Mirrors `TenantChannelEndpointRead` (subset) — the manual WhatsApp chat links for a tenant. */
export type TenantChannelEndpointRead = {
  id: number
  tenant_id: number
  channel_type: string
  provider: string
  external_account_id: string | null
  external_chat_namespace: string | null
  chat_display_name: string | null
  is_active: boolean
  is_most_recent_inbound: boolean
  created_at: string
  updated_at: string
}

// --- normalized bubble the UI renders ---

export type ThreadBubble =
  | {
      kind: 'whatsapp'
      id: number
      key: string
      direction: string
      text: string
      at: string
      aiGenerated: boolean
    }
  | {
      kind: 'email'
      id: number
      key: string
      direction: string
      text: string
      subject: string | null
      sender: string | null
      at: string
      aiGenerated: boolean
      /** Owning email thread — lets the UI offer a "forward this thread" action per bubble. */
      threadId: number | null
      /** Original HTML body, if any — rendered on demand in the full-screen email viewer. */
      html: string | null
    }

/**
 * Flatten the nested grouped-thread into a single chronological list of bubbles.
 *
 * WhatsApp messages can appear either as their own `whatsapp_group` items or nested inside an
 * email thread's `whatsapp_blocks` (the server interleaves them by time); each message lives in
 * exactly one place, but we de-dupe by id defensively so a bubble can never render twice.
 */
export function flattenThread(thread: MixedTimelineRead): ThreadBubble[] {
  const bubbles: ThreadBubble[] = []
  const seen = new Set<string>()

  const pushWhatsapp = (m: TimelineWhatsappMessageRead) => {
    const key = `wa:${m.id}`
    if (seen.has(key)) return
    seen.add(key)
    bubbles.push({
      kind: 'whatsapp',
      id: m.id,
      key,
      direction: m.direction,
      text: m.message,
      at: m.created_at,
      aiGenerated: m.ai_generated,
    })
  }

  const pushEmail = (m: TimelineMessageRead, threadSubject: string | null, threadId: number | null) => {
    const key = `em:${m.id}`
    if (seen.has(key)) return
    seen.add(key)
    bubbles.push({
      kind: 'email',
      id: m.id,
      key,
      direction: m.direction,
      text: m.body_display || m.body_text || m.body,
      subject: m.subject ?? threadSubject,
      sender: m.sender_email,
      at: m.sent_at,
      aiGenerated: m.ai_generated,
      threadId,
      html: m.body_html,
    })
  }

  for (const item of thread.items) {
    if (item.type === 'email_thread') {
      for (const m of item.messages) pushEmail(m, item.subject, item.thread_id)
      for (const block of item.whatsapp_blocks) for (const wm of block.messages) pushWhatsapp(wm)
    } else {
      for (const wm of item.messages) pushWhatsapp(wm)
    }
  }

  bubbles.sort(
    (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime() || a.key.localeCompare(b.key),
  )
  return bubbles
}

// --- requests ---

/** GET /api/communications/tenants/{id}/grouped-thread — unified WhatsApp + email timeline. */
export async function getGroupedThread(tenantId: number): Promise<MixedTimelineRead> {
  const { data } = await apiClient.get<MixedTimelineRead>(
    `/api/communications/tenants/${tenantId}/grouped-thread`,
  )
  return data
}

/** A repliable email thread, distilled from the grouped-thread's email_thread items. */
export type EmailThreadOption = {
  threadId: number
  subject: string | null
  accountEmail: string | null
}

/**
 * Pull the distinct email threads out of a grouped timeline, so the composer can offer an email
 * reply target. Recipient is resolved server-side from the thread's latest message, so the client
 * only needs the thread id.
 */
export function extractEmailThreads(thread: MixedTimelineRead): EmailThreadOption[] {
  const seen = new Set<number>()
  const out: EmailThreadOption[] = []
  for (const item of thread.items) {
    if (item.type !== 'email_thread' || seen.has(item.thread_id)) continue
    seen.add(item.thread_id)
    out.push({
      threadId: item.thread_id,
      subject: item.subject,
      accountEmail: item.provider_account_email,
    })
  }
  return out
}

/** GET /api/communications/tenants/{id}/thread-version — cheap change marker for polling. */
export async function getThreadVersion(tenantId: number): Promise<{ latest_at: string | null }> {
  const { data } = await apiClient.get<{ latest_at: string | null }>(
    `/api/communications/tenants/${tenantId}/thread-version`,
  )
  return data
}

/** GET /api/communications/tenants/{id}/whatsapp-endpoints — active manual chat links. */
export async function getWhatsappEndpoints(
  tenantId: number,
): Promise<TenantChannelEndpointRead[]> {
  const { data } = await apiClient.get<TenantChannelEndpointRead[]>(
    `/api/communications/tenants/${tenantId}/whatsapp-endpoints`,
  )
  return data
}

/**
 * POST /api/communications/tenants/{id}/send — plain-text WhatsApp send.
 *
 * A specific `whatsappEndpointId` is always passed so the message targets the exact manually
 * linked chat (CLAUDE.md WhatsApp invariants: send only through an explicit endpoint, never an
 * inferred one). Email composing is deferred for the MVP.
 */
export async function sendWhatsappMessage(args: {
  tenantId: number
  message: string
  whatsappEndpointId: number
}): Promise<CommunicationRead> {
  const { data } = await apiClient.post<CommunicationRead>(
    `/api/communications/tenants/${args.tenantId}/send`,
    {
      channel: 'whatsapp',
      direction: 'outbound',
      message: args.message,
      whatsapp_endpoint_id: args.whatsappEndpointId,
    },
  )
  return data
}

/**
 * POST /api/communications/tenants/{id}/send — plain-text email reply into an existing thread.
 *
 * The recipient, In-Reply-To/References headers, and Gmail account are all resolved server-side
 * from `email_thread_id`; the client only supplies the thread and the body (subject defaults to the
 * thread's subject when omitted). Rich HTML composing stays web-only — mobile sends plain text.
 */
export async function sendEmailReply(args: {
  tenantId: number
  emailThreadId: number
  message: string
  subject?: string | null
  cc?: string | null
}): Promise<CommunicationRead> {
  const { data } = await apiClient.post<CommunicationRead>(
    `/api/communications/tenants/${args.tenantId}/send`,
    {
      channel: 'email',
      direction: 'outbound',
      message: args.message,
      email_thread_id: args.emailThreadId,
      subject: args.subject ?? undefined,
      cc: args.cc ?? undefined,
    },
  )
  return data
}

/**
 * POST /api/communications/tenants/{id}/forward — forward an email thread to the admin-configured
 * forwarding address (set in Admin Settings server-side; no recipient input from the client).
 */
export async function forwardEmailThread(args: {
  tenantId: number
  emailThreadId: number
  body: string
}): Promise<CommunicationRead> {
  const { data } = await apiClient.post<CommunicationRead>(
    `/api/communications/tenants/${args.tenantId}/forward`,
    { email_thread_id: args.emailThreadId, body: args.body },
  )
  return data
}

export type AiDraftResponse = {
  generated_text: string
  formatted_text: string | null
  template_id: number
}

/**
 * POST /api/communications/tenants/{id}/ai-draft — generate an AI reply draft for review.
 *
 * Returns the draft text only; it is NEVER auto-sent — the caller drops it into the composer for
 * the user to review, edit, and send explicitly.
 */
export async function generateAiDraft(args: {
  tenantId: number
  channel: 'email' | 'whatsapp'
  templateId?: number
  roughDraft?: string
}): Promise<AiDraftResponse> {
  const { data } = await apiClient.post<AiDraftResponse>(
    `/api/communications/tenants/${args.tenantId}/ai-draft`,
    {
      channel: args.channel,
      template_id: args.templateId ?? undefined,
      rough_draft: args.roughDraft ?? undefined,
    },
  )
  return data
}
