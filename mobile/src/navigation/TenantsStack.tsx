import { createNativeStackNavigator } from '@react-navigation/native-stack'

import type { TenantsStackParamList } from './types'
import { TenantListScreen } from '../screens/TenantListScreen'
import { TenantDetailScreen } from '../screens/TenantDetailScreen'
import { ThreadScreen } from '../screens/ThreadScreen'
import { EmailViewerScreen } from '../screens/EmailViewerScreen'

const Stack = createNativeStackNavigator<TenantsStackParamList>()

/** Tenants tab: list → detail → thread. */
export function TenantsStack() {
  return (
    <Stack.Navigator screenOptions={{ headerTitleAlign: 'center' }}>
      <Stack.Screen name="TenantList" component={TenantListScreen} options={{ title: 'Tenants' }} />
      <Stack.Screen name="TenantDetail" component={TenantDetailScreen} options={{ title: 'Tenant' }} />
      <Stack.Screen name="Thread" component={ThreadScreen} options={{ title: 'Thread' }} />
      <Stack.Screen name="EmailViewer" component={EmailViewerScreen} options={{ title: 'Email' }} />
    </Stack.Navigator>
  )
}
