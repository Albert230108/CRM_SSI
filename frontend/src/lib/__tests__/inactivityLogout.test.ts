import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installInactivityLogout, stopInactivityLogout } from '../inactivityLogout'
import { useAuthStore } from '../../store/authStore'

const TEST_USER = {
  id: 7,
  email: 'user@example.com',
  full_name: null,
  is_active: true,
  is_admin: false,
  whatsapp_notifications_enabled: false,
  default_gmail_account_id: null,
  default_whatsapp_account_id: null,
}

describe('installInactivityLogout', () => {
  const originalFetch = window.fetch
  const rawFetch = vi.fn()

  beforeEach(() => {
    vi.useFakeTimers()
    rawFetch.mockReset()
    window.fetch = rawFetch
    useAuthStore.setState({
      token: 'abc',
      user: TEST_USER,
      isAuthenticated: true,
      sessionExpired: false,
    })
  })

  afterEach(() => {
    stopInactivityLogout()
    vi.useRealTimers()
    window.fetch = originalFetch
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false, sessionExpired: false })
  })

  it('refreshes the session after activity while authenticated', async () => {
    rawFetch.mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'new-token' }), { status: 200 }))

    installInactivityLogout()
    document.dispatchEvent(new Event('mousemove'))
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)

    expect(rawFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/refresh'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer abc' }),
      }),
    )
    expect(useAuthStore.getState().token).toBe('new-token')
    expect(useAuthStore.getState().user?.email).toBe('user@example.com')
  })

  it('does not refresh when there has been no activity', async () => {
    installInactivityLogout()
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000)

    expect(rawFetch).not.toHaveBeenCalled()
    expect(useAuthStore.getState().token).toBe('abc')
  })
})
