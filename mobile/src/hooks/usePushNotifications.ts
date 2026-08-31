import { useEffect, useRef } from 'react'
import { Platform } from 'react-native'
import * as Notifications from 'expo-notifications'

import { registerDevice } from '../api/devices'
import { registerForPushNotificationsAsync } from '../lib/push'
import { navigateToThread } from '../navigation/navigationRef'
import { useAuthStore } from '../store/authStore'

function handleResponse(response: Notifications.NotificationResponse): void {
  const data = response.notification.request.content.data as { tenant_id?: unknown } | undefined
  const tenantId = data?.tenant_id
  if (typeof tenantId === 'number') navigateToThread(tenantId)
}

/**
 * Wires push notifications to the auth lifecycle (Phase 2):
 *  - on login, request permission, get the ExpoPushToken, and register it with the backend;
 *  - on a notification tap (foreground, background, or cold start), deep-link to the tenant thread.
 *
 * Unregistration happens in the auth store's logout (it must run while the JWT is still valid).
 */
export function usePushNotifications(): void {
  const status = useAuthStore((s) => s.status)
  const didRegister = useRef(false)

  useEffect(() => {
    if (status !== 'authed' || didRegister.current) return
    didRegister.current = true
    void (async () => {
      const token = await registerForPushNotificationsAsync()
      if (!token) return
      try {
        await registerDevice(token, Platform.OS)
      } catch {
        // Best-effort: a failed registration shouldn't disrupt the session.
      }
    })()
  }, [status])

  // Allow re-registration after a logout/login cycle.
  useEffect(() => {
    if (status === 'unauthed') didRegister.current = false
  }, [status])

  // Tap handling for warm/background taps and cold starts.
  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener(handleResponse)
    void Notifications.getLastNotificationResponseAsync().then((response) => {
      if (response) handleResponse(response)
    })
    return () => sub.remove()
  }, [])
}
