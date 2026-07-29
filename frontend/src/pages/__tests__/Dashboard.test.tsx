import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import Dashboard from '../Dashboard'
import { useAuthStore } from '../../store/authStore'
import {
  loadDashboardLayoutPreference,
  storageKeyFor,
  TENANT_SIDEBAR_DEFAULT_WIDTH,
} from '../../lib/dashboardLayoutPreferences'

vi.mock('../../components/TenantList', () => ({ default: () => <div>tenant-list</div> }))
vi.mock('../../components/FinanceBox', () => ({ default: () => <div>finance-box</div> }))
vi.mock('../../components/OneDriveBox', () => ({ default: () => <div>onedrive-box</div> }))
vi.mock('../../components/ThreadView', () => ({ default: () => <div>thread-view</div> }))

function renderDashboard() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
      </Routes>
    </MemoryRouter>,
  )
}

function setUser(id: number, email: string) {
  useAuthStore.setState({
    token: 'test-token',
    user: { id, email, full_name: null, is_active: true, is_admin: false },
    isAuthenticated: true,
  })
}

beforeEach(() => {
  window.localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: async () => null } as Response)),
  )
  // jsdom has no ResizeObserver; the Dashboard falls back to a fixed default width without it.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  vi.stubGlobal('matchMedia', (query: string) =>
    ({
      matches: query.includes('min-width'),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }) as unknown as MediaQueryList,
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useAuthStore.setState({ token: null, user: null, isAuthenticated: false })
})

describe('Dashboard column layout', () => {
  it('renders the default layout when no saved preference exists', async () => {
    setUser(1, 'alice@example.com')
    renderDashboard()

    expect(await screen.findByText('tenant-list')).toBeInTheDocument()
    expect(screen.getByLabelText('Resize tenant sidebar')).toBeInTheDocument()
    expect(screen.getByLabelText('Resize thread panel')).toBeInTheDocument()
    expect(loadDashboardLayoutPreference('1')).toBeNull()
  })

  it('falls back safely when the stored preference is malformed', async () => {
    setUser(1, 'alice@example.com')
    window.localStorage.setItem(storageKeyFor('1'), '{ not valid json')
    renderDashboard()

    const handle = await screen.findByLabelText('Resize tenant sidebar')
    expect(handle).toHaveAttribute('aria-valuenow', String(TENANT_SIDEBAR_DEFAULT_WIDTH))
  })

  it('adjusts the tenant sidebar width with arrow keys and persists it for that user', async () => {
    setUser(1, 'alice@example.com')
    renderDashboard()

    const handle = await screen.findByLabelText('Resize tenant sidebar')
    const before = Number(handle.getAttribute('aria-valuenow'))

    act(() => {
      handle.focus()
    })
    await import('@testing-library/user-event').then(({ default: userEvent }) =>
      userEvent.setup().keyboard('{ArrowRight}'),
    )

    const after = Number(handle.getAttribute('aria-valuenow'))
    expect(after).toBeGreaterThan(before)

    const saved = loadDashboardLayoutPreference('1')
    expect(saved?.tenantSidebarExpandedWidth).toBe(after)
  })

  it('scopes saved layout preferences per user', async () => {
    setUser(1, 'alice@example.com')
    const { unmount: unmountA } = renderDashboard()
    const handleA = await screen.findByLabelText('Resize tenant sidebar')
    act(() => {
      handleA.focus()
    })
    await import('@testing-library/user-event').then(({ default: userEvent }) =>
      userEvent.setup().keyboard('{ArrowRight}{ArrowRight}'),
    )
    const userAWidth = Number(handleA.getAttribute('aria-valuenow'))
    unmountA()

    setUser(2, 'bob@example.com')
    renderDashboard()
    const handleB = await screen.findByLabelText('Resize tenant sidebar')
    expect(Number(handleB.getAttribute('aria-valuenow'))).toBe(TENANT_SIDEBAR_DEFAULT_WIDTH)
    expect(Number(handleB.getAttribute('aria-valuenow'))).not.toBe(userAWidth)

    expect(loadDashboardLayoutPreference('1')?.tenantSidebarExpandedWidth).toBe(userAWidth)
    expect(loadDashboardLayoutPreference('2')).toBeNull()
  })

  it('preserves the saved expanded width across a collapse/expand cycle', async () => {
    setUser(1, 'alice@example.com')
    renderDashboard()

    const handle = await screen.findByLabelText('Resize tenant sidebar')
    act(() => {
      handle.focus()
    })
    const userEvent = (await import('@testing-library/user-event')).default
    await userEvent.setup().keyboard('{ArrowRight}{ArrowRight}')
    const resizedWidth = Number(handle.getAttribute('aria-valuenow'))

    const collapseButton = screen.getByLabelText('Collapse tenants panel')
    await userEvent.setup().click(collapseButton)
    expect(screen.getByLabelText('Expand tenants panel')).toBeInTheDocument()

    await userEvent.setup().click(screen.getByLabelText('Expand tenants panel'))
    const handleAfterExpand = await screen.findByLabelText('Resize tenant sidebar')
    expect(Number(handleAfterExpand.getAttribute('aria-valuenow'))).toBe(resizedWidth)
  })
})
