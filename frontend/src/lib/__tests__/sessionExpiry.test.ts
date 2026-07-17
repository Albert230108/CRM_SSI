import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { installSessionExpiryDetection, isAuthenticatedRequest } from '../sessionExpiry'
import { useAuthStore } from '../../store/authStore'

describe('isAuthenticatedRequest', () => {
  it('detects an Authorization header on a plain headers object', () => {
    expect(isAuthenticatedRequest('/api/x', { headers: { Authorization: 'Bearer t' } })).toBe(true)
  })

  it('detects an Authorization header on a Headers instance', () => {
    expect(isAuthenticatedRequest('/api/x', { headers: new Headers({ Authorization: 'Bearer t' }) })).toBe(true)
  })

  it('detects an Authorization header on a Request object', () => {
    const request = new Request('https://example.com/api/x', { headers: { Authorization: 'Bearer t' } })
    expect(isAuthenticatedRequest(request)).toBe(true)
  })

  it('returns false when no Authorization header is present', () => {
    expect(isAuthenticatedRequest('/api/auth/login', { method: 'POST' })).toBe(false)
  })
})

describe('installSessionExpiryDetection', () => {
  const originalWindowFetch = window.fetch
  const rawFetch = vi.fn()

  beforeEach(() => {
    rawFetch.mockReset()
    useAuthStore.setState({ token: 'abc', isAuthenticated: true, sessionExpired: false })
  })

  afterAll(() => {
    window.fetch = originalWindowFetch
  })

  it('flags an active session as expired when an authenticated request comes back 401', async () => {
    window.fetch = rawFetch
    installSessionExpiryDetection()
    rawFetch.mockResolvedValueOnce(new Response(null, { status: 401 }))

    await window.fetch('/api/thing', { headers: { Authorization: 'Bearer abc' } })

    expect(useAuthStore.getState().sessionExpired).toBe(true)
  })

  it('does not flag when a 401 comes from a request with no Authorization header', async () => {
    installSessionExpiryDetection()
    rawFetch.mockResolvedValueOnce(new Response(null, { status: 401 }))

    await window.fetch('/api/auth/login', { method: 'POST' })

    expect(useAuthStore.getState().sessionExpired).toBe(false)
  })

  it('does not flag on a non-401 response', async () => {
    installSessionExpiryDetection()
    rawFetch.mockResolvedValueOnce(new Response(null, { status: 200 }))

    await window.fetch('/api/thing', { headers: { Authorization: 'Bearer abc' } })

    expect(useAuthStore.getState().sessionExpired).toBe(false)
  })
})
