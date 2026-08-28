import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import Dashboard from '../Dashboard'
import { useAuthStore } from '../../store/authStore'

type TileKey = 'finance' | 'notes' | 'onedrive' | 'thread'
type TileRegistration = { tenantId: number; onReady?: (tenantId: number) => void }

const registry: Record<TileKey, TileRegistration | null> = { finance: null, notes: null, onedrive: null, thread: null }

function mockTile(key: TileKey, label: string) {
  return {
    default: ({ tenantId, onReady }: { tenantId?: number; onReady?: (tenantId: number) => void }) => {
      useEffect(() => {
        if (tenantId !== undefined) registry[key] = { tenantId, onReady }
      }, [tenantId, onReady])
      return <div>{label}</div>
    },
  }
}

vi.mock('../../components/TenantList', () => ({ default: () => <div>tenant-list</div> }))
vi.mock('../../components/FinanceBox', () => mockTile('finance', 'finance-box'))
vi.mock('../../components/TenantNotesPanel', () => mockTile('notes', 'notes-panel'))
vi.mock('../../components/OneDriveBox', () => mockTile('onedrive', 'onedrive-box'))
vi.mock('../../components/ThreadView', () => mockTile('thread', 'thread-view'))

// Simulates the tile finishing its fetch for the tenantId it was last rendered with.
function resolveTile(key: TileKey) {
  const entry = registry[key]
  if (!entry) throw new Error(`${key} tile has not registered a tenantId yet`)
  act(() => {
    entry.onReady?.(entry.tenantId)
  })
}

function NavButton({ to, label }: { to: string; label: string }) {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(to)}>
      {label}
    </button>
  )
}

function renderDashboardAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/dashboard/tenant/:tenantId"
          element={
            <>
              <NavButton to="/dashboard/tenant/1" label="go-tenant-1" />
              <NavButton to="/dashboard/tenant/2" label="go-tenant-2" />
              <Dashboard />
            </>
          }
        />
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

const LOADING_OVERLAY = { name: 'Loading tenant data' }

beforeEach(() => {
  registry.finance = null
  registry.notes = null
  registry.onedrive = null
  registry.thread = null
  window.localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: async () => null } as Response)))
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

describe('Dashboard tenant-switch loading overlay', () => {
  it('keeps all four tiles blurred together until every tile is ready, and re-blurs on tenant switch', async () => {
    setUser(1, 'alice@example.com')
    renderDashboardAt('/dashboard/tenant/1')

    expect(await screen.findAllByRole('status', LOADING_OVERLAY)).toHaveLength(4)

    // Three of four tiles finishing must not clear the overlay: all four share one gate,
    // so it's all-or-nothing rather than each tile un-blurring independently.
    resolveTile('finance')
    resolveTile('onedrive')
    resolveTile('notes')
    expect(screen.getAllByRole('status', LOADING_OVERLAY)).toHaveLength(4)

    resolveTile('thread')
    expect(screen.queryAllByRole('status', LOADING_OVERLAY)).toHaveLength(0)

    await userEvent.click(screen.getByText('go-tenant-2'))
    expect(await screen.findAllByRole('status', LOADING_OVERLAY)).toHaveLength(4)

    resolveTile('finance')
    resolveTile('onedrive')
    resolveTile('notes')
    expect(screen.getAllByRole('status', LOADING_OVERLAY)).toHaveLength(4)

    // A stale onReady callback from tenant 1's aborted fetch (finally still runs on abort)
    // must not be mistaken for tenant 2 readiness.
    act(() => registry.thread?.onReady?.(1))
    expect(screen.getAllByRole('status', LOADING_OVERLAY)).toHaveLength(4)

    resolveTile('thread')
    expect(screen.queryAllByRole('status', LOADING_OVERLAY)).toHaveLength(0)
  })
})
