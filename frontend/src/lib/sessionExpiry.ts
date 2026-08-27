import { useAuthStore } from '../store/authStore'
import { logDiag } from './refreshDiagnostics'

let installed = false

export function isAuthenticatedRequest(input: RequestInfo | URL, init?: RequestInit): boolean {
  const headers = input instanceof Request ? input.headers : new Headers(init?.headers)
  return headers.has('Authorization')
}

// No centralized API client exists yet (every page calls fetch() directly), so this
// patches window.fetch once at startup to catch a 401 on any Bearer-authenticated
// request and flag the session as expired, instead of each call site silently
// swallowing it into local component error state.
export function installSessionExpiryDetection() {
  if (installed) return
  installed = true

  const originalFetch = window.fetch.bind(window)

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await originalFetch(input, init)

    if (response.status === 401 && isAuthenticatedRequest(input, init)) {
      logDiag('401_detected', {
        url: input instanceof Request ? input.url : String(input),
      })
      useAuthStore.getState().flagSessionExpired()
    }

    return response
  }
}
