import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ThreadView from '../ThreadView'

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
