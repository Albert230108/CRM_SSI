import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from '../authStore'

describe('authStore session expiry', () => {
  beforeEach(() => {
    window.localStorage.clear()
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false, sessionExpired: false })
  })

  it('flags the session as expired while a session is active', () => {
    useAuthStore.setState({ token: 'abc', isAuthenticated: true })
    useAuthStore.getState().flagSessionExpired()
    expect(useAuthStore.getState().sessionExpired).toBe(true)
  })

  it('ignores a stray 401 when there is no active session', () => {
    useAuthStore.getState().flagSessionExpired()
    expect(useAuthStore.getState().sessionExpired).toBe(false)
  })

  it('clears the expired flag on logout', () => {
    useAuthStore.setState({ token: 'abc', isAuthenticated: true, sessionExpired: true })
    useAuthStore.getState().logout()
    expect(useAuthStore.getState().sessionExpired).toBe(false)
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('clears the expired flag on a fresh login', () => {
    useAuthStore.setState({ sessionExpired: true })
    useAuthStore.getState().setAuth('new-token')
    expect(useAuthStore.getState().sessionExpired).toBe(false)
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
  })
})
