import { Text } from 'react-native'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'

import { TenantsStack } from './TenantsStack'
import { NotificationsStack } from './NotificationsStack'
import { SettingsScreen } from '../screens/SettingsScreen'
import { useUnreadCount } from '../hooks/useNotifications'

/** The authenticated app shell: bottom tabs, each (except Settings) wrapping its own stack. */
export type AppTabsParamList = {
  Tenants: undefined
  Notifications: undefined
  Settings: undefined
}

const Tab = createBottomTabNavigator<AppTabsParamList>()

const icon = (glyph: string) => ({ color }: { color: string }) => (
  <Text style={{ fontSize: 20, color }}>{glyph}</Text>
)

export function AppTabs() {
  const { data: unreadCount } = useUnreadCount()

  return (
    <Tab.Navigator screenOptions={{ headerShown: false, tabBarActiveTintColor: '#2563eb' }}>
      <Tab.Screen
        name="Tenants"
        component={TenantsStack}
        options={{ tabBarIcon: icon('👥') }}
      />
      <Tab.Screen
        name="Notifications"
        component={NotificationsStack}
        options={{
          tabBarIcon: icon('🔔'),
          tabBarBadge: unreadCount && unreadCount > 0 ? unreadCount : undefined,
        }}
      />
      <Tab.Screen
        name="Settings"
        component={SettingsScreen}
        options={{ headerShown: true, headerTitleAlign: 'center', tabBarIcon: icon('⚙️') }}
      />
    </Tab.Navigator>
  )
}
