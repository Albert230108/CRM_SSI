import { ActivityIndicator, StyleSheet, View } from 'react-native'
import { NavigationContainer } from '@react-navigation/native'
import { createNativeStackNavigator } from '@react-navigation/native-stack'

import { useAuthStore } from '../store/authStore'
import { LoginScreen } from '../screens/LoginScreen'
import { AppTabs } from './AppTabs'
import { navigationRef } from './navigationRef'

/**
 * Top-level routing: a loading splash during hydrate, then either the auth stack (Login) or the
 * authenticated tab shell — chosen by auth status, the RN equivalent of the web app's
 * route guards.
 */
export type RootStackParamList = {
  Login: undefined
  App: undefined
}

const Stack = createNativeStackNavigator<RootStackParamList>()

export function RootNavigator() {
  const status = useAuthStore((s) => s.status)

  if (status === 'loading') {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" color="#2563eb" />
      </View>
    )
  }

  return (
    <NavigationContainer ref={navigationRef}>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {status === 'authed' ? (
          <Stack.Screen name="App" component={AppTabs} />
        ) : (
          <Stack.Screen name="Login" component={LoginScreen} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  )
}

const styles = StyleSheet.create({
  splash: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#f3f4f6' },
})
