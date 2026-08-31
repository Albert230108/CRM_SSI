import { AppState, type AppStateStatus } from 'react-native'

import { TOKEN_REFRESH_INTERVAL_MS } from '../config'

/**
 * Proactive token-refresh controller — the RN equivalent of the web app's
 * `frontend/src/lib/inactivityLogout.ts`.
 *
 * The backend has no refresh token, and `/api/auth/refresh` only works while the current token
 * is still valid, so we refresh BEFORE expiry rather than reacting to a 401. Two triggers:
 *  - an interval that fires while the app is foregrounded, and
 *  - an AppState transition back to "active" (a phone backgrounded for a while should top up
 *    its token as soon as the user returns — as long as it hasn't already expired).
 *
 * The actual refresh work is injected (the auth store owns it) to keep this module free of any
 * store/client dependency. `onRefresh` should resolve quietly; a genuine 401 during refresh is
 * handled by the API client's response interceptor (→ logout), so failures here are swallowed.
 */
type SessionControllerOptions = {
  onRefresh: () => Promise<void>
}

export function createSessionController({ onRefresh }: SessionControllerOptions) {
  let intervalId: ReturnType<typeof setInterval> | null = null
  let appStateSub: { remove: () => void } | null = null
  let running = false

  const safeRefresh = () => {
    void onRefresh().catch(() => {
      // Intentionally quiet: an expired-token 401 is turned into a logout by the client
      // interceptor; transient network errors will be retried on the next tick / foreground.
    })
  }

  const handleAppStateChange = (next: AppStateStatus) => {
    if (next === 'active') safeRefresh()
  }

  return {
    /** Begin proactive refresh. Idempotent. Call after a successful login / hydrate. */
    start(): void {
      if (running) return
      running = true
      intervalId = setInterval(safeRefresh, TOKEN_REFRESH_INTERVAL_MS)
      appStateSub = AppState.addEventListener('change', handleAppStateChange)
    },

    /** Stop proactive refresh and detach listeners. Idempotent. Call on logout. */
    stop(): void {
      if (!running) return
      running = false
      if (intervalId) {
        clearInterval(intervalId)
        intervalId = null
      }
      appStateSub?.remove()
      appStateSub = null
    },
  }
}

export type SessionController = ReturnType<typeof createSessionController>
