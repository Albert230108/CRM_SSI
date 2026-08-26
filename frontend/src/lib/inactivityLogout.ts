import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const ACTIVITY_THROTTLE_MS = 30_000
const REFRESH_INTERVAL_MS = 5 * 60 * 1000
const ACTIVITY_EVENTS = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'] as const

let installed = false
let cleanup: (() => void) | null = null
let lastActivityAt = Number.NEGATIVE_INFINITY
let lastRefreshAt = Number.NEGATIVE_INFINITY

function recordActivity() {
  const now = Date.now()
  if (now - lastActivityAt < ACTIVITY_THROTTLE_MS) return
  lastActivityAt = now
}

async function refreshSession() {
  const state = useAuthStore.getState()
  if (!state.isAuthenticated || !state.token) return
  if (lastActivityAt <= lastRefreshAt) return

  const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${state.token}`,
    },
  })

  if (!response.ok) return

  const data: { access_token: string } = await response.json()
  const currentUser = useAuthStore.getState().user
  useAuthStore.getState().setAuth(data.access_token, currentUser)
  lastRefreshAt = Date.now()
}

export function installInactivityLogout() {
  if (installed) return cleanup ?? undefined
  installed = true

  const activityHandler = () => {
    recordActivity()
  }

  for (const eventName of ACTIVITY_EVENTS) {
    document.addEventListener(eventName, activityHandler, { passive: true })
  }

  const intervalId = window.setInterval(() => {
    void refreshSession().catch(() => {})
  }, REFRESH_INTERVAL_MS)

  cleanup = () => {
    for (const eventName of ACTIVITY_EVENTS) {
      document.removeEventListener(eventName, activityHandler)
    }
    window.clearInterval(intervalId)
    installed = false
    cleanup = null
    lastActivityAt = Number.NEGATIVE_INFINITY
    lastRefreshAt = Number.NEGATIVE_INFINITY
  }

  return cleanup
}

export function stopInactivityLogout() {
  cleanup?.()
}
