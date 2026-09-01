import { createNativeStackNavigator } from '@react-navigation/native-stack'

import type { TenantsStackParamList } from './types'
import { TenantListScreen } from '../screens/TenantListScreen'
import { ThreadScreen } from '../screens/ThreadScreen'
import { BookingDetailScreen } from '../screens/BookingDetailScreen'
import { NotesScreen } from '../screens/NotesScreen'
import { BrainScreen } from '../screens/BrainScreen'
import { EmailViewerScreen } from '../screens/EmailViewerScreen'

const Stack = createNativeStackNavigator<TenantsStackParamList>()

/** Tenants tab: list → chat directly; the chat header opens the per-tenant info screens. */
export function TenantsStack() {
  return (
    <Stack.Navigator screenOptions={{ headerTitleAlign: 'center' }}>
      <Stack.Screen name="TenantList" component={TenantListScreen} options={{ title: 'Tenants' }} />
      <Stack.Screen name="Thread" component={ThreadScreen} options={{ title: 'Thread' }} />
      <Stack.Screen name="BookingDetail" component={BookingDetailScreen} options={{ title: 'Beds24 details' }} />
      <Stack.Screen name="Notes" component={NotesScreen} options={{ title: 'Notes' }} />
      <Stack.Screen name="Brain" component={BrainScreen} options={{ title: 'Brain' }} />
      <Stack.Screen name="EmailViewer" component={EmailViewerScreen} options={{ title: 'Email' }} />
    </Stack.Navigator>
  )
}
