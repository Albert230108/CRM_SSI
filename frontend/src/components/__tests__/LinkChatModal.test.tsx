import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LinkChatModal from '../LinkChatModal'

const ACCOUNT = { external_account_id: 'acct-1', provider: 'whatsapp-web', label: 'Front Desk' }

const CHATS = [
  { chat_id: '5511999990000@c.us', chat_name: 'Alice Guest', provider: 'whatsapp-web', external_account_id: 'acct-1', last_message_timestamp: null, last_message_preview: null, already_linked: false, linked_thread_id: null },
  { chat_id: '5511888880000@c.us', chat_name: 'Bob Guest', provider: 'whatsapp-web', external_account_id: 'acct-1', last_message_timestamp: null, last_message_preview: null, already_linked: false, linked_thread_id: null },
]

const EXISTING_LINK = {
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

function buildFetchMock(options: { links?: unknown[] } = {}) {
  const links = options.links ?? []
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const method = init?.method ?? 'GET'

    if (url.includes('/whatsapp/accounts/') && url.includes('/chats')) {
      const search = new URL(url, 'http://localhost').searchParams.get('search') || ''
      const filtered = search ? CHATS.filter((chat) => chat.chat_id.includes(search) || chat.chat_name.includes(search)) : CHATS
      return jsonResponse(filtered)
    }
    if (url.includes('/api/whatsapp/accounts') && method === 'GET') {
      return jsonResponse([ACCOUNT])
    }
    if (url.match(/\/whatsapp-links$/) && method === 'GET') {
      return jsonResponse(links)
    }
    if (url.match(/\/whatsapp-links$/) && method === 'POST') {
      return jsonResponse({ ...EXISTING_LINK, id: 99 })
    }
    if (url.match(/\/whatsapp-links\/\d+$/) && method === 'DELETE') {
      return jsonResponse({ ...EXISTING_LINK, is_active: false })
    }
    if (url.match(/\/whatsapp-links\/\d+\/resync$/) && method === 'POST') {
      return jsonResponse({ resync: { ok: true, fetched: 10, imported: 8, deduped: 2, skipped_no_content: 0 } })
    }
    return jsonResponse({ detail: `unhandled ${method} ${url}` }, false)
  })
}

describe('LinkChatModal', () => {
  beforeEach(() => {
    vi.useRealTimers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('finds an exact CHAT_ID via search', async () => {
    const fetchMock = buildFetchMock()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<LinkChatModal open threadId={7} onClose={() => {}} />)

    await user.click(await screen.findByRole('button', { name: /Front Desk/i }))
    await screen.findByText('5511999990000@c.us')

    const search = screen.getByPlaceholderText('Search by CHAT_ID or name')
    await user.type(search, '5511888880000')

    await waitFor(() => {
      expect(screen.getByText('5511888880000@c.us')).toBeInTheDocument()
      expect(screen.queryByText('5511999990000@c.us')).not.toBeInTheDocument()
    })

    vi.unstubAllGlobals()
  })

  it('does not create a link until Confirm link is pressed', async () => {
    const fetchMock = buildFetchMock()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const onChanged = vi.fn()

    render(<LinkChatModal open threadId={7} onClose={() => {}} onChanged={onChanged} />)

    await user.click(await screen.findByRole('button', { name: /Front Desk/i }))
    await user.click(await screen.findByText('5511999990000@c.us'))

    const postCallsBefore = fetchMock.mock.calls.filter(([, init]: [RequestInfo | URL, RequestInit | undefined]) => init?.method === 'POST').length
    expect(postCallsBefore).toBe(0)

    await user.click(screen.getByRole('button', { name: 'Confirm link' }))

    await waitFor(() => {
      const postCalls = fetchMock.mock.calls.filter(([, init]: [RequestInfo | URL, RequestInit | undefined]) => init?.method === 'POST')
      expect(postCalls.length).toBe(1)
      expect(onChanged).toHaveBeenCalled()
    })

    vi.unstubAllGlobals()
  })

  it('refreshes linked state via onChanged after a successful link', async () => {
    const fetchMock = buildFetchMock()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const onChanged = vi.fn()

    render(<LinkChatModal open threadId={7} onClose={() => {}} onChanged={onChanged} />)

    await user.click(await screen.findByRole('button', { name: /Front Desk/i }))
    await user.click(await screen.findByText('5511999990000@c.us'))
    await user.click(screen.getByRole('button', { name: 'Confirm link' }))

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1))

    vi.unstubAllGlobals()
  })

  it('calls the targeted resync endpoint and shows a result before refreshing', async () => {
    const fetchMock = buildFetchMock({ links: [EXISTING_LINK] })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const onChanged = vi.fn()

    render(<LinkChatModal open threadId={7} onClose={() => {}} onChanged={onChanged} />)

    const resyncButton = await screen.findByRole('button', { name: 'Resync full history' })
    await user.click(resyncButton)

    await waitFor(() => {
      expect(screen.getByText(/Done: 10 fetched, 8 imported, 2 already synced/)).toBeInTheDocument()
    })
    expect(onChanged).toHaveBeenCalled()

    const resyncCalls = fetchMock.mock.calls.filter(([input, init]: [RequestInfo | URL, RequestInit | undefined]) => {
      const url = typeof input === 'string' ? input : input.toString()
      return url.includes(`/whatsapp-links/${EXISTING_LINK.id}/resync`) && init?.method === 'POST'
    })
    expect(resyncCalls.length).toBe(1)

    vi.unstubAllGlobals()
  })

  it('requires confirmation before unlinking, then refreshes', async () => {
    const fetchMock = buildFetchMock({ links: [EXISTING_LINK] })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const onChanged = vi.fn()

    render(<LinkChatModal open threadId={7} onClose={() => {}} onChanged={onChanged} />)

    await user.click(await screen.findByRole('button', { name: 'Unlink' }))
    expect(screen.getByText('Unlink this chat?')).toBeInTheDocument()

    const deleteCallsBefore = fetchMock.mock.calls.filter(([, init]: [RequestInfo | URL, RequestInit | undefined]) => init?.method === 'DELETE').length
    expect(deleteCallsBefore).toBe(0)

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('Unlink this chat?')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Unlink' }))
    await user.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      const deleteCalls = fetchMock.mock.calls.filter(([, init]: [RequestInfo | URL, RequestInit | undefined]) => init?.method === 'DELETE')
      expect(deleteCalls.length).toBe(1)
      expect(onChanged).toHaveBeenCalled()
    })

    vi.unstubAllGlobals()
  })

  it('clears transient selection state when closed and reopened', async () => {
    const fetchMock = buildFetchMock()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    const { rerender } = render(<LinkChatModal open threadId={7} onClose={() => {}} />)

    await user.click(await screen.findByRole('button', { name: /Front Desk/i }))
    const search = await screen.findByPlaceholderText('Search by CHAT_ID or name')
    await user.type(search, 'Alice')
    await screen.findByText('5511999990000@c.us')

    rerender(<LinkChatModal open={false} threadId={7} onClose={() => {}} />)
    rerender(<LinkChatModal open threadId={7} onClose={() => {}} />)

    await screen.findByRole('button', { name: /Front Desk/i })
    expect(screen.queryByPlaceholderText('Search by CHAT_ID or name')).not.toBeInTheDocument()

    vi.unstubAllGlobals()
  })
})
