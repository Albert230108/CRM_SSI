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
    if (url.includes('/memory-qa')) return jsonResponse([])
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

  it('opens the fullscreen tenant brain panel from the inline composer', async () => {
    vi.stubGlobal('fetch', buildFetchMock([]))
    const user = userEvent.setup()

    render(<ThreadView tenantId={7} />)

    await user.click(await screen.findByRole('button', { name: 'Fullscreen' }))
    expect(await screen.findByText("Fullscreen chat with this tenant's context loaded.")).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Exit fullscreen' }))
    expect(screen.queryByText("Fullscreen chat with this tenant's context loaded.")).not.toBeInTheDocument()
  })

  it('sends a tenant brain question from the inline header composer', async () => {
    const qaHistory: Array<{ id: number; role: 'user' | 'assistant'; content: string; created_at: string }> = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/memory-qa')) {
        if ((init?.method ?? 'GET') === 'POST') {
          const body = JSON.parse((init?.body as string) || '{}') as { question?: string }
          const assistantMessage = { id: qaHistory.length + 2, role: 'assistant' as const, content: 'Check-in is at 3pm.', created_at: '2026-07-20T11:00:00Z' }
          qaHistory.push({ id: qaHistory.length + 1, role: 'user', content: body.question || '', created_at: '2026-07-20T10:59:00Z' }, assistantMessage)
          return jsonResponse(assistantMessage)
        }
        return jsonResponse(qaHistory)
      }
      if (url.includes('/api/tenants/7')) return jsonResponse(TENANT)
      if (url.includes('/grouped-thread')) return jsonResponse({ tenant_id: 7, tenant_name: TENANT.name, items: [] })
      if (url.includes('/whatsapp-endpoints')) return jsonResponse([])
      if (url.match(/\/whatsapp-links$/)) return jsonResponse([])
      return jsonResponse({ detail: `unhandled ${url}` }, false)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ThreadView tenantId={7} />)

    const input = await screen.findByPlaceholderText('Ask about this tenant...')
    await user.type(input, 'What time is check-in?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Check-in is at 3pm.')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalled()
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

  it('hides the Run planner button when the planner is off for the tenant', async () => {
    useAuthStore.setState({ token: 'test-token' })
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/api/tenants/7/ai-settings')) return jsonResponse({ tenant_id: 7, available_template_ids: [], default_email_template_id: null, default_whatsapp_template_id: AI_TEMPLATE.id, auto_draft_email: false, auto_draft_whatsapp: false, auto_send_email: false, auto_send_whatsapp: false, planner_mode: 'off' })
        if (url.includes('/api/ai-reply-templates')) return jsonResponse([AI_TEMPLATE])
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
    await user.click(await screen.findByRole('button', { name: 'Reply' }))

    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByRole('button', { name: 'Draft with AI' })
    expect(within(dialog).queryByRole('button', { name: 'Run planner' })).not.toBeInTheDocument()
  })

  it('queues the planner and shows the background notice instead of filling the textarea', async () => {
    useAuthStore.setState({ token: 'test-token' })
    const planSpy = vi.fn(() => jsonResponse({ status: 'pending', draft_id: 12 }))

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/api/tenants/7/ai-settings')) return jsonResponse({ tenant_id: 7, available_template_ids: [], default_email_template_id: null, default_whatsapp_template_id: AI_TEMPLATE.id, auto_draft_email: false, auto_draft_whatsapp: false, auto_send_email: false, auto_send_whatsapp: false, planner_mode: 'manual' })
        if (url.includes('/api/ai-reply-templates')) return jsonResponse([AI_TEMPLATE])
        if (url.includes('/ai-plan')) return planSpy(input, init)
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
    await user.click(await screen.findByRole('button', { name: 'Reply' }))

    const dialog = await screen.findByRole('dialog')
    const textarea = within(dialog).getByPlaceholderText('Write your reply...')
    await user.type(textarea, 'mention the lockbox')

    await user.click(await within(dialog).findByRole('button', { name: 'Run planner' }))

    await waitFor(() => expect(planSpy).toHaveBeenCalledTimes(1))
    expect(within(dialog).queryByDisplayValue('Planned reply text')).not.toBeInTheDocument()
    expect(await within(dialog).findByText('Planner running - check AI Drafts.')).toBeInTheDocument()

    const [, requestInit] = planSpy.mock.calls[0]
    // The planner still receives the operator's rough draft and the selected channel.
    expect(JSON.parse((requestInit as RequestInit).body as string)).toEqual({ channel: 'whatsapp', rough_draft: 'mention the lockbox', attachment_ids: [] })
  })

  it('shows the background notice when the planner is queued', async () => {
    useAuthStore.setState({ token: 'test-token' })
    const planSpy = vi.fn(() => jsonResponse({ status: 'pending', draft_id: 13 }))
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/api/tenants/7/ai-settings')) return jsonResponse({ tenant_id: 7, available_template_ids: [], default_email_template_id: null, default_whatsapp_template_id: AI_TEMPLATE.id, auto_draft_email: false, auto_draft_whatsapp: false, auto_send_email: false, auto_send_whatsapp: false, planner_mode: 'manual' })
        if (url.includes('/api/ai-reply-templates')) return jsonResponse([AI_TEMPLATE])
        if (url.includes('/ai-plan')) return planSpy(input)
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
    await user.click(await screen.findByRole('button', { name: 'Reply' }))

    const dialog = await screen.findByRole('dialog')
    await user.click(await within(dialog).findByRole('button', { name: 'Run planner' }))

    expect(await within(dialog).findByText('Planner running - check AI Drafts.')).toBeInTheDocument()
    expect(within(dialog).queryByText(/reviewer never approved/i)).not.toBeInTheDocument()
  })

  it('shows a pending auto-draft banner and fills the textarea when used', async () => {
    useAuthStore.setState({ token: 'test-token' })
    const pendingDraft = {
      id: 55,
      tenant_id: 7,
      channel: 'whatsapp',
      generated_text: 'Plain fallback text',
      formatted_text: '<p>Auto-generated: <strong>check-in</strong> is 3pm</p>',
      status: 'pending',
      scheduled_send_at: null,
      created_at: '2026-07-20T10:00:00Z',
    }
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
    expect(
      within(dialog).getByText((_, element) => element?.tagName === 'P' && element.textContent === 'Auto-generated: check-in is 3pm'),
    ).toBeInTheDocument()
    expect(dialog).not.toHaveTextContent('<p>')
    expect(within(dialog).queryByText(pendingDraft.generated_text)).not.toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Use this draft' }))

    await waitFor(() => expect(markUsedSpy).toHaveBeenCalledTimes(1))
    expect(within(dialog).getByDisplayValue(pendingDraft.generated_text)).toBeInTheDocument()
  })
})

const TENANT_8 = { id: 8, name: 'Sam Roe', email: 'sam@example.com', phone: '+2000000', booking_id: 'BK-456' }

const emailThread = (threadId: number, subject: string) => ({
  type: 'email_thread',
  thread_id: threadId,
  provider_account_id: 1,
  provider_account_email: 'host@example.com',
  provider_account_display_name: 'Host',
  matched_tenant_email: 'guest@example.com',
  provider_thread_id: `gmail-${threadId}`,
  subject,
  preview_text: 'hello',
  anchor_timestamp: '2026-07-20T10:00:00Z',
  whatsapp_blocks: [],
  messages: [
    {
      id: threadId * 100,
      subject,
      body: 'hello',
      body_text: 'hello',
      body_html: null,
      body_display: 'hello',
      direction: 'inbound',
      sent_at: '2026-07-20T10:00:00Z',
      from_email: 'guest@example.com',
      to_email: 'host@example.com',
      attachments: [],
    },
  ],
})

// tenantId -> { thread, drafts } so a rerender with a different tenant serves that tenant's data.
function buildTenantFetchMock(fixtures: Record<number, { thread: unknown; drafts: unknown[]; draftsOk?: boolean; attachments?: unknown[]; attachmentsOk?: boolean }>) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    const tenantMatch = url.match(/\/tenants\/(\d+)/)
    const tenantId = tenantMatch ? Number(tenantMatch[1]) : null
    const fixture = tenantId != null ? fixtures[tenantId] : null

    if (url.endsWith('/attachments')) return jsonResponse(fixture?.attachments ?? [], fixture?.attachmentsOk ?? true)
    if (url.includes('/reply-drafts')) return jsonResponse(fixture?.drafts ?? [], fixture?.draftsOk ?? true)
    if (url.includes('/grouped-thread')) {
      return jsonResponse({ tenant_id: tenantId, tenant_name: '', items: fixture ? [fixture.thread] : [] })
    }
    if (url.includes('/whatsapp-endpoints')) return jsonResponse([])
    if (url.match(/\/whatsapp-links$/)) return jsonResponse([])
    if (url.includes('/api/ai-auto-drafts')) return jsonResponse([])
    if (url.includes('/ai-settings')) return jsonResponse({ tenant_id: tenantId, available_template_ids: [], default_email_template_id: null, default_whatsapp_template_id: null, auto_draft_email: false, auto_draft_whatsapp: false, auto_send_email: false, auto_send_whatsapp: false })
    if (url.includes('/api/ai-reply-templates')) return jsonResponse([])
    if (url.includes('/api/tenants/8')) return jsonResponse(TENANT_8)
    if (url.includes('/api/tenants/7')) return jsonResponse(TENANT)
    return jsonResponse({ detail: `unhandled ${url}` }, false)
  })
}

describe('ThreadView per-thread reply drafts', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    useAuthStore.setState({ token: null })
  })

  it('does not carry a reply draft over to the next tenant', async () => {
    // Regression: replyMessage used to be one component-wide slot that survived a tenant
    // switch, so the draft written for tenant 7 showed up in tenant 8's reply box.
    useAuthStore.setState({ token: 'test-token' })
    // Tenant 8's draft fetch deliberately fails, so only the tenant-switch reset - not
    // hydration happening to overwrite the map - can keep tenant 7's text out of the box.
    vi.stubGlobal('fetch', buildTenantFetchMock({
      7: { thread: emailThread(101, 'Tenant 7 thread'), drafts: [] },
      8: { thread: emailThread(202, 'Tenant 8 thread'), drafts: [], draftsOk: false },
    }))
    const user = userEvent.setup()

    const { rerender } = render(<ThreadView tenantId={7} />)
    await screen.findByText('Jane Doe')

    await user.click(await screen.findByText('Tenant 7 thread'))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByPlaceholderText('Write your reply...'), 'private to tenant 7')
    expect(within(dialog).getByDisplayValue('private to tenant 7')).toBeInTheDocument()

    rerender(<ThreadView tenantId={8} />)

    await screen.findByText('Sam Roe')
    // Tenant 7's thread panel must not stay open over tenant 8's timeline either.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('private to tenant 7')).not.toBeInTheDocument()

    await user.click(await screen.findByText('Tenant 8 thread'))
    const nextDialog = await screen.findByRole('dialog')
    expect(within(nextDialog).getByPlaceholderText('Write your reply...')).toHaveValue('')
  })

  it("restores each thread's own persisted draft when that thread is opened", async () => {
    useAuthStore.setState({ token: 'test-token' })
    vi.stubGlobal('fetch', buildTenantFetchMock({
      8: {
        thread: emailThread(202, 'Tenant 8 thread'),
        drafts: [{
          id: 1,
          tenant_id: 8,
          channel: 'email',
          email_thread_id: 202,
          whatsapp_endpoint_id: null,
          subject: 'Re: stay',
          body: 'saved earlier for 202',
          attachment_ids: [55],
          attachments: [{ id: 55, filename: 'contract.pdf', size_bytes: 1234, mime_type: 'application/pdf' }],
        }],
      },
    }))
    const user = userEvent.setup()

    render(<ThreadView tenantId={8} />)
    await screen.findByText('Sam Roe')

    await user.click(await screen.findByText('Tenant 8 thread'))

    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByPlaceholderText('Write your reply...')).toHaveValue('saved earlier for 202'))
    expect(within(dialog).getByDisplayValue('Re: stay')).toBeInTheDocument()
    expect(within(dialog).getByTitle('contract.pdf')).toBeInTheDocument()
  })

  it('persists attachment ids when attachments are added from history', async () => {
    useAuthStore.setState({ token: 'test-token' })
    const fetchMock = buildTenantFetchMock({
      7: {
        thread: emailThread(101, 'Tenant 7 thread'),
        drafts: [],
        attachments: [{ id: 55, filename: 'contract.pdf', mime_type: 'application/pdf', size_bytes: 1234, origin: 'upload', created_at: '2026-08-26T00:00:00Z' }],
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ThreadView tenantId={7} />)
    await screen.findByText('Jane Doe')

    await user.click(await screen.findByText('Tenant 7 thread'))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'From history' }))
    await user.click(await within(dialog).findByRole('button', { name: /contract\.pdf/ }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
      expect(put).toBeDefined()
      const [url, init] = put as [string, RequestInit]
      expect(url).toContain('/api/communications/tenants/7/reply-drafts')
      expect(JSON.parse(init.body as string)).toMatchObject({ channel: 'email', email_thread_id: 101, attachment_ids: [55] })
    }, { timeout: 3000 })
  })

  it('persists the draft against the thread it was written for', async () => {
    useAuthStore.setState({ token: 'test-token' })
    const fetchMock = buildTenantFetchMock({ 7: { thread: emailThread(101, 'Tenant 7 thread'), drafts: [] } })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<ThreadView tenantId={7} />)
    await screen.findByText('Jane Doe')

    await user.click(await screen.findByText('Tenant 7 thread'))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByPlaceholderText('Write your reply...'), 'autosave me')

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
      expect(put).toBeDefined()
      const [url, init] = put as [string, RequestInit]
      expect(url).toContain('/api/communications/tenants/7/reply-drafts')
      expect(JSON.parse(init.body as string)).toMatchObject({ channel: 'email', email_thread_id: 101, body: 'autosave me' })
    }, { timeout: 3000 })
  })
})
