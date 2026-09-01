import { createNativeStackNavigator } from '@react-navigation/native-stack'

import type { NotificationsStackParamList } from './types'
import { NotificationsScreen } from '../screens/NotificationsScreen'
import { ThreadScreen } from '../screens/ThreadScreen'
import { BookingDetailScreen } from '../screens/BookingDetailScreen'
import { NotesScreen } from '../screens/NotesScreen'
import { BrainScreen } from '../screens/BrainScreen'
import { EmailViewerScreen } from '../screens/EmailViewerScreen'

const Stack = createNativeStackNavigator<NotificationsStackParamList>()

/**
 * Notifications tab: list → chat (tapping a notification opens the tenant's chat). The per-tenant
 * info screens are registered here too, so the chat header dropdown works when a chat is reached
 * from a notification. ThreadScreen and the info screens are typed against the Tenants stack params,
 * which are structurally identical to this stack's, so they are reused here without change.
 */
export function NotificationsStack() {
  return (
    <Stack.Navigator screenOptions={{ headerTitleAlign: 'center' }}>
      <Stack.Screen
        name="NotificationsList"
        component={NotificationsScreen}
        options={{ title: 'Notifications' }}
      />
      <Stack.Screen name="Thread" component={ThreadScreen} options={{ title: 'Thread' }} />
      <Stack.Screen name="BookingDetail" component={BookingDetailScreen} options={{ title: 'Beds24 details' }} />
      <Stack.Screen name="Notes" component={NotesScreen} options={{ title: 'Notes' }} />
      <Stack.Screen name="Brain" component={BrainScreen} options={{ title: 'Brain' }} />
      <Stack.Screen name="EmailViewer" component={EmailViewerScreen} options={{ title: 'Email' }} />
    </Stack.Navigator>
  )
}
