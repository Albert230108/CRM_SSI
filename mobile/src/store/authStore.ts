import { create } from 'zustand'

import { login as loginRequest, me as fetchMe, refresh as refreshRequest, type CurrentUser } from '../api/auth'
import { sessionBridge } from '../api/sessionBridge'
import { unregisterDevice } from '../api/devices'
import { createSessionController } from '../lib/session'
import { clearRegisteredPushToken, getRegisteredPushToken } from '../lib/push'
import { clearStoredToken, getStoredToken, setStoredToken } from '../lib/secureStorage'

/**
 * Auth/session store — the RN port of `frontend/src/store/authStore.ts`. The logic mirrors the
 * web store; only the storage layer differs (expo-secure-store instead of localStorage).
 *
 * Session longevity follows plan decision (a) "accept re-logins" (docs/android-mobile-app-plan.md):
 * a proactive refresh timer keeps a foregrounded session alive under the 120-min token cap, and a
 * genuine 401 (e.g. app backgrounded past expiry) clears the session and routes to Login.
 */

/** 'loading' covers the initial SecureStore hydrate before we know if a session exists. */
export type AuthStatus = 'loading' | 'authed' | 'unauthed'

type AuthState = {
  status: AuthStatus
  token: string | null
  user: CurrentUser | null
  /** Restore a persisted session on launch. Safe to call once at app start. */
  hydrate: () => Promise<void>
  /** Log in with credentials; persists the token and loads the user. Throws on bad credentials. */
  login: (email: string, password: string) => Promise<void>
  /** Clear the session (user action, or forced by a 401). */
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'loading',
  token: null,
  user: null,

  hydrate: async () => {
    const token = await getStoredToken()
    if (!token) {
      set({ status: 'unauthed', token: null, user: null })
      return
    }
    set({ token })
    try {
      const user = await fetchMe()
      set({ status: 'authed', user })
      sessionController.start()
    } catch {
      // Token present but rejected/unusable → treat as logged out. (The client's 401
      // interceptor may also have fired logout(); this is the belt-and-braces path.)
      await clearStoredToken()
      set({ status: 'unauthed', token: null, user: null })
    }
  },

  login: async (email, password) => {
    const { access_token } = await loginRequest(email, password)
    await setStoredToken(access_token)
    set({ token: access_token })
    const user = await fetchMe()
    set({ status: 'authed', user })
    sessionController.start()
  },

  logout: async () => {
    sessionController.stop()
    // Unregister this device's push token while the JWT is still valid (the endpoint is
    // bearer-authed), then clear it. Best-effort: never block logout on a network failure.
    const pushToken = getRegisteredPushToken()
    if (pushToken) {
      try {
        await unregisterDevice(pushToken)
      } catch {
        // ignore — the token will also be pruned server-side once Expo reports it stale
      }
      clearRegisteredPushToken()
    }
    await clearStoredToken()
    set({ status: 'unauthed', token: null, user: null })
  },
}))

/**
 * Proactive refresh: swap in a fresh token while the current one is still valid. A 401 raised
 * during refresh is converted to a logout by the API client's response interceptor.
 */
const sessionController = createSessionController({
  onRefresh: async () => {
    if (!useAuthStore.getState().token) return
    const { access_token } = await refreshRequest()
    await setStoredToken(access_token)
    useAuthStore.setState({ token: access_token })
  },
})

// Wire the API client to this store (see api/sessionBridge.ts for why this indirection exists).
sessionBridge.setTokenGetter(() => useAuthStore.getState().token)
sessionBridge.setUnauthorizedHandler(() => {
  // Only act on a live session so a late 401 after an explicit logout doesn't loop.
  if (useAuthStore.getState().status !== 'unauthed') {
    void useAuthStore.getState().logout()
  }
})
