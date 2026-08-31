import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'

import { PlaceholderScreen } from '../screens/PlaceholderScreen'
import { SettingsScreen } from '../screens/SettingsScreen'

/**
 * The authenticated app shell: bottom tabs. Dashboard (tenant list) and Notifications get their
 * real screens in Phase 1 / Phase 2 respectively; for Phase 0 they are placeholders so the
 * navigation shell is complete and demonstrable.
 */
export type AppTabsParamList = {
  Dashboard: undefined
  Notifications: undefined
  Settings: undefined
}

const Tab = createBottomTabNavigator<AppTabsParamList>()

function DashboardTab() {
  return (
    <PlaceholderScreen
      title="Dashboard"
      note="Tenant list & search — built in Phase 1 (replaces TenantList.tsx)."
    />
  )
}

function NotificationsTab() {
  return (
    <PlaceholderScreen
      title="Notifications"
      note="Notifications list & unread badge — Phase 1 (polling) + Phase 2 (FCM push)."
    />
  )
}

export function AppTabs() {
  return (
    <Tab.Navigator screenOptions={{ headerTitleAlign: 'center' }}>
      <Tab.Screen name="Dashboard" component={DashboardTab} />
      <Tab.Screen name="Notifications" component={NotificationsTab} />
      <Tab.Screen name="Settings" component={SettingsScreen} />
    </Tab.Navigator>
  )
}
