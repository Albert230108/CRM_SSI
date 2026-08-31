import { useEffect } from 'react'
import { AppState, type AppStateStatus } from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { KeyboardProvider } from 'react-native-keyboard-controller'
import { QueryClient, focusManager } from '@tanstack/react-query'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import AsyncStorage from '@react-native-async-storage/async-storage'

import { RootNavigator } from './src/navigation/RootNavigator'
import { useAuthStore } from './src/store/authStore'
import { usePushNotifications } from './src/hooks/usePushNotifications'

/**
 * App entry: install providers (React Query for server state, SafeArea for insets, keyboard
 * controller for consistent keyboard avoidance), restore any persisted session once on launch,
 * then hand off to RootNavigator for auth-based routing.
 */
const CACHE_MAX_AGE = 1000 * 60 * 60 * 24 // 24h — how long a persisted thread may show before refresh

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      // Foreground polling intervals are set per-query. Keep cached threads around long enough that
      // re-opening a recently viewed tenant renders instantly (background-refetches, no spinner).
      staleTime: 30_000,
      gcTime: CACHE_MAX_AGE,
    },
  },
})

// Persist the query cache to AsyncStorage so previously-opened threads appear immediately on cold
// start, then refresh in the background — instead of showing a blocking spinner every launch.
const persister = createAsyncStoragePersister({ storage: AsyncStorage })

export default function App() {
  const hydrate = useAuthStore((s) => s.hydrate)
  usePushNotifications()

  useEffect(() => {
    void hydrate()
  }, [hydrate])

  // Tie React Query's focus state to app foreground/background so interval polling (and the
  // per-query refetchIntervals) pause while the app is backgrounded, saving battery/data.
  useEffect(() => {
    const onChange = (state: AppStateStatus) => focusManager.setFocused(state === 'active')
    const sub = AppState.addEventListener('change', onChange)
    return () => sub.remove()
  }, [])

  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{ persister, maxAge: CACHE_MAX_AGE }}
    >
      <KeyboardProvider>
        <SafeAreaProvider>
          <StatusBar style="auto" />
          <RootNavigator />
        </SafeAreaProvider>
      </KeyboardProvider>
    </PersistQueryClientProvider>
  )
}
