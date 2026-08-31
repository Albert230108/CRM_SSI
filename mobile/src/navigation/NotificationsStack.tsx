import { createNativeStackNavigator } from '@react-navigation/native-stack'

import type { NotificationsStackParamList } from './types'
import { NotificationsScreen } from '../screens/NotificationsScreen'
import { ThreadScreen } from '../screens/ThreadScreen'
import { EmailViewerScreen } from '../screens/EmailViewerScreen'

const Stack = createNativeStackNavigator<NotificationsStackParamList>()

/** Notifications tab: list → thread (tapping a notification opens the tenant's thread). */
export function NotificationsStack() {
  return (
    <Stack.Navigator screenOptions={{ headerTitleAlign: 'center' }}>
      <Stack.Screen
        name="NotificationsList"
        component={NotificationsScreen}
        options={{ title: 'Notifications' }}
      />
      {/* ThreadScreen is typed against the Tenants stack params, which are structurally identical
          to this stack's Thread params, so it is reused here without change. */}
      <Stack.Screen name="Thread" component={ThreadScreen} options={{ title: 'Thread' }} />
      <Stack.Screen name="EmailViewer" component={EmailViewerScreen} options={{ title: 'Email' }} />
    </Stack.Navigator>
  )
}
