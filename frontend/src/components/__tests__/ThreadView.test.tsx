import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ThreadView from '../ThreadView'
import { useAuthStore } from '../../store/authStore'

const TENANT = { id: 7, name: 'Jane Doe', email: 'jane@example.com', phone: '+1000000', booking_id: 'BK-123' }

const ACTIVE_LINK = {
  id: 42,
  thread_id: 7,
  provider: 'whatsapp-web',
  external_account_id: 'acct-1',
  chat_id: '5511777770000@c.us',
  chat_display_name: 'Carol Guest',
  is_active: true,
  linked_by_user_id: 3,
  unlinked_at: null,
  unlinked_by_user_id: null,
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
}

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: async () => body } as Response)
}

function buildFetchMock(links: unknown[]) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/api/tenants/7')) return jsonResponse(TENANT)
    if (url.includes('/grouped-thread')) return jsonResponse({ tenant_id: 7, tenant_name: TENANT.name, items: [] })
    if (url.includes('/whatsapp-endpoints')) return jsonResponse([])
    if (url.match(/\/whatsapp-links$/)) return jsonResponse(links)
    if (url.includes('/api/whatsapp/accounts')) return jsonResponse([])
    return jsonResponse({ detail: `unhandled ${url}` }, false)
  })
}

describe('ThreadView WhatsApp link UX', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('does not render the inline linked-chat banner', async () => {
    vi.stubGlobal('fetch', buildFetchMock([ACTIVE_LINK]))

    render(<ThreadView tenantId={7} />)

    await screen.findByText('Jane Doe')

    expect(screen.queryByText('Resync full history')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Unlink' })).not.toBeInTheDocument()
    expect(screen.queryByText(ACTIVE_LINK.chat_id)).not.toBeInTheDocument()
  })

  it('opens the modal when the header control is clicked', async () => {
    vi.stubGlobal('fetch', buildFetchMock([]))
    const user = userEvent.setup()

    render(<ThreadView tenantId={7} />)

    const trigger = await screen.findByRole('button', { name: 'Link chat' })
    await user.click(trigger)

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('renders existing links inside the modal, not below the thread', async () => {
    vi.stubGlobal('fetch', buildFetchMock([ACTIVE_LINK]))
    const user = userEvent.setup()

    render(<ThreadView tenantId={7} />)

    const trigger = await screen.findByRole('button', { name: 'Manage chats' })
    await user.click(trigger)

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(ACTIVE_LINK.chat_id)).toBeInTheDocument()
    expect(screen.getAllByText(ACTIVE_LINK.chat_id)).toHaveLength(1)
  })
})

const AI_TEMPLATE = { id: 9, name: 'Friendly host' }

const WHATSAPP_GROUP = {
  type: 'whatsapp_group',
  group_id: 'group-1',
  start_timestamp: '2026-07-20T10:00:00Z',
  end_timestamp: '2026-07-20T10:05:00Z',
  message_count: 1,
  messages: [
    {
      id: 1,
      tenant_id: 7,
      channel: 'whatsapp',
      direction: 'inbound',
      provider: 'whatsapp-web',
      external_account_id: 'acct-1',
      external_phone_id: null,
      external_chat_namespace: null,
      whatsapp_chat_id: '5511777770000@c.us',
      provider_message_id: 'wamid-1',
      subject: null,
      message: 'What time is check-in?',
      created_at: '2026-07-20T10:00:00Z',
    },
  ],
}

describe('ThreadView Draft with AI', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    useAuthStore.setState({ token: null })
  })

  it('generates a draft via the AI template picker and fills the reply textarea', async () => {
    // The AI template/settings loaders (like the pre-existing forward-flow loaders) only fire
    // once a token is present.
    useAuthStore.setState({ token: 'test-token' })
    const generateSpy = vi.fn(() => jsonResponse({ generated_text: 'Check-in is at 3pm!', template_id: AI_TEMPLATE.id }))

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/api/tenants/7/ai-settings')) return jsonResponse({ tenant_id: 7, available_template_ids: [], default_email_template_id: null, default_whatsapp_template_id: AI_TEMPLATE.id, auto_draft_email: false, auto_draft_whatsapp: false, auto_send_email: false, auto_send_whatsapp: false })
        if (url.includes('/api/ai-reply-templates')) return jsonResponse([AI_TEMPLATE])
        if (url.includes('/api/tenants/7')) return jsonResponse(TENANT)
        if (url.includes('/grouped-thread')) return jsonResponse({ tenant_id: 7, tenant_name: TENANT.name, items: [WHATSAPP_GROUP] })
        if (url.includes('/whatsapp-endpoints')) return jsonResponse([])
        if (url.match(/\/whatsapp-links$/)) return jsonResponse([])
        if (url.includes('/ai-draft')) return generateSpy(input, init)
        return jsonResponse({ detail: `unhandled ${url}` }, false)
      }),
    )
    const user = userEvent.setup()

    render(<ThreadView tenantId={7} />)
    await screen.findByText('Jane Doe')

    const replyButton = await screen.findByRole('button', { name: 'Reply' })
    await user.click(replyButton)

    const dialog = await screen.findByRole('dialog')
    // Options only populate once /api/ai-reply-templates resolves, and the tenant's default
    // selection only applies once /api/tenants/7/ai-settings resolves - wait for both.
    await within(dialog).findByText(AI_TEMPLATE.name)
    await waitFor(() => expect(within(dialog).getByDisplayValue(AI_TEMPLATE.name)).toBeInTheDocument())

    const textarea = within(dialog).getByPlaceholderText('Write your reply...')
    await user.type(textarea, 'let them know 3pm')

    await user.click(within(dialog).getByRole('button', { name: 'Draft with AI' }))

    await waitFor(() => expect(generateSpy).toHaveBeenCalledTimes(1))
    expect(await within(dialog).findByDisplayValue('Check-in is at 3pm!')).toBeInTheDocument()

    const [, requestInit] = generateSpy.mock.calls[0]
    const requestBody = JSON.parse((requestInit as RequestInit).body as string)
    expect(requestBody).toEqual({ channel: 'whatsapp', template_id: AI_TEMPLATE.id, rough_draft: 'let them know 3pm' })
  })

  it('shows a pending auto-draft banner and fills the textarea when used', async () => {
    useAuthStore.setState({ token: 'test-token' })
    const pendingDraft = { id: 55, tenant_id: 7, channel: 'whatsapp', generated_text: 'Auto-generated: check-in is 3pm', status: 'pending', scheduled_send_at: null, created_at: '2026-07-20T10:00:00Z' }
    const markUsedSpy = vi.fn(() => jsonResponse({ ...pendingDraft, status: 'used_as_manual_seed' }))

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/api/tenants/7/ai-settings')) return jsonResponse({ tenant_id: 7, available_template_ids: [], default_email_template_id: null, default_whatsapp_template_id: null, auto_draft_email: false, auto_draft_whatsapp: true, auto_send_email: false, auto_send_whatsapp: false })
        if (url.includes('/api/ai-reply-templates')) return jsonResponse([AI_TEMPLATE])
        if (url.includes('/mark-used')) return markUsedSpy()
        if (url.includes('/api/ai-auto-drafts')) return jsonResponse([pendingDraft])
        if (url.includes('/api/tenants/7')) return jsonResponse(TENANT)
        if (url.includes('/grouped-thread')) return jsonResponse({ tenant_id: 7, tenant_name: TENANT.name, items: [WHATSAPP_GROUP] })
        if (url.includes('/whatsapp-endpoints')) return jsonResponse([])
        if (url.match(/\/whatsapp-links$/)) return jsonResponse([])
        return jsonResponse({ detail: `unhandled ${url}` }, false)
      }),
    )
    const user = userEvent.setup()

    render(<ThreadView tenantId={7} />)
    await screen.findByText('Jane Doe')

    const replyButton = await screen.findByRole('button', { name: 'Reply' })
    await user.click(replyButton)

    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText('Pending AI draft')
    expect(within(dialog).getByText(pendingDraft.generated_text)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Use this draft' }))

    await waitFor(() => expect(markUsedSpy).toHaveBeenCalledTimes(1))
    expect(within(dialog).getByDisplayValue(pendingDraft.generated_text)).toBeInTheDocument()
  })
})
