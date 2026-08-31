import { useEffect } from 'react'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { RootNavigator } from './src/navigation/RootNavigator'
import { useAuthStore } from './src/store/authStore'

/**
 * App entry: install providers (React Query for server state, SafeArea for insets), restore any
 * persisted session once on launch, then hand off to RootNavigator for auth-based routing.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      // Foreground polling intervals are set per-query in Phase 1; sensible defaults here.
      staleTime: 30_000,
    },
  },
})

export default function App() {
  const hydrate = useAuthStore((s) => s.hydrate)

  useEffect(() => {
    void hydrate()
  }, [hydrate])

  return (
    <QueryClientProvider client={queryClient}>
      <SafeAreaProvider>
        <StatusBar style="auto" />
        <RootNavigator />
      </SafeAreaProvider>
    </QueryClientProvider>
  )
}
