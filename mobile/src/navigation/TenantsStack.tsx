import { createNativeStackNavigator } from '@react-navigation/native-stack'

import type { TenantsStackParamList } from './types'
import { TenantListScreen } from '../screens/TenantListScreen'
import { ThreadScreen } from '../screens/ThreadScreen'

const Stack = createNativeStackNavigator<TenantsStackParamList>()

/** Tenants tab: list → thread. */
export function TenantsStack() {
  return (
    <Stack.Navigator screenOptions={{ headerTitleAlign: 'center' }}>
      <Stack.Screen name="TenantList" component={TenantListScreen} options={{ title: 'Tenants' }} />
      <Stack.Screen name="Thread" component={ThreadScreen} options={{ title: 'Thread' }} />
    </Stack.Navigator>
  )
}
