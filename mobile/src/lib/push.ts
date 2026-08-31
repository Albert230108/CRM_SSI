import { Platform } from 'react-native'
import Constants from 'expo-constants'
import * as Device from 'expo-device'
import * as Notifications from 'expo-notifications'

/**
 * Expo push-notification helpers (Phase 2). We use Expo's push service: the client obtains an
 * ExpoPushToken and the backend POSTs to Expo's push API, which relays to FCM. Remote delivery in
 * a real build still requires a Firebase project wired into EAS — until that's configured this
 * degrades gracefully (returns null rather than throwing), so the rest of the app is unaffected.
 */

// How notifications behave while the app is foregrounded.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
})

// The token last registered with the backend, kept so logout can unregister it.
let registeredToken: string | null = null

export function getRegisteredPushToken(): string | null {
  return registeredToken
}

export function clearRegisteredPushToken(): void {
  registeredToken = null
}

function resolveProjectId(): string | undefined {
  const extra = Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined
  return extra?.eas?.projectId ?? Constants.easConfig?.projectId
}

/**
 * Ensure permission + an Android channel, then fetch the ExpoPushToken. Returns null (rather than
 * throwing) on a simulator, when permission is denied, or when no EAS projectId is configured yet.
 */
export async function registerForPushNotificationsAsync(): Promise<string | null> {
  // Push tokens are only issued to physical devices.
  if (!Device.isDevice) return null

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'Default',
      importance: Notifications.AndroidImportance.DEFAULT,
    })
  }

  const existing = await Notifications.getPermissionsAsync()
  let granted = existing.granted
  if (!granted) {
    const requested = await Notifications.requestPermissionsAsync()
    granted = requested.granted
  }
  if (!granted) return null

  const projectId = resolveProjectId()
  if (!projectId) return null

  try {
    const tokenData = await Notifications.getExpoPushTokenAsync({ projectId })
    registeredToken = tokenData.data
    return registeredToken
  } catch {
    return null
  }
}
