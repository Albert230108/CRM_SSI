import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ScheduledPlannerRuns from '../ScheduledPlannerRuns'
import { useAuthStore } from '../../store/authStore'

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: async () => body } as Response)
}

describe('ScheduledPlannerRuns preview debounce', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useAuthStore.setState({
      token: 'test-token',
      user: { id: 2, email: 'member@example.com', full_name: null, is_active: true, is_admin: false },
      isAuthenticated: true,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false })
  })

  it('posts preview filters after the debounce window', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.endsWith('/api/bulk-planner-schedules') && !init?.method) return jsonResponse([])
      if (url.endsWith('/api/tenants/statuses')) return jsonResponse(['Confirmed', 'Request'])
      if (url.endsWith('/api/bulk-planner-schedules/preview')) {
        return jsonResponse({ matched_tenant_count: 1, tenants: [{ id: 7, name: 'Tenant A', booking_id: 'BK-7', booking_status: 'Confirmed' }] })
      }
      return jsonResponse({ detail: `unhandled ${url}` }, false)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<ScheduledPlannerRuns />)

    await Promise.resolve()
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(0)
    expect(screen.getByRole('heading', { name: 'Create schedule' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Last message within days'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('Direction'), { target: { value: 'inbound' } })

    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/api/bulk-planner-schedules/preview')).length,
    ).toBe(0)

    await vi.advanceTimersByTimeAsync(299)
    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/api/bulk-planner-schedules/preview')).length,
    ).toBe(0)

    await vi.advanceTimersByTimeAsync(1)

    expect(
      fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/api/bulk-planner-schedules/preview')).length,
    ).toBe(1)

    const previewCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/api/bulk-planner-schedules/preview'))
    expect(previewCall).toBeTruthy()
    const [, requestInit] = previewCall as [RequestInfo | URL, RequestInit]
    expect(JSON.parse(String(requestInit.body))).toEqual({
      status_filter: [],
      last_message_within_days: 7,
      last_message_direction: 'inbound',
    })
  })
})
