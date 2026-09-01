import { CommonActions, createNavigationContainerRef } from '@react-navigation/native'

/**
 * A container-level navigation ref so non-React code (notification tap handlers) can navigate.
 * The nested target is App → Tenants tab → Thread; we dispatch a CommonActions.navigate so the
 * nested screen/params are resolved without the container ref's strict single-route typing.
 */
export const navigationRef = createNavigationContainerRef()

// A tap can be delivered (notably on a cold start) before the navigation container has mounted.
// We stash the target and flush it from the container's onReady so the deep link is never lost.
let pendingThread: { tenantId: number; tenantName?: string } | null = null

export function navigateToThread(tenantId: number, tenantName?: string): void {
  if (!navigationRef.isReady()) {
    pendingThread = { tenantId, tenantName }
    return
  }
  navigationRef.dispatch(
    CommonActions.navigate({
      name: 'App',
      params: {
        screen: 'Tenants',
        params: { screen: 'Thread', params: { tenantId, tenantName } },
      },
    }),
  )
}

/** Flush a deep link captured before the navigator was ready. Called from NavigationContainer.onReady. */
export function flushPendingThread(): void {
  if (!pendingThread || !navigationRef.isReady()) return
  const { tenantId, tenantName } = pendingThread
  pendingThread = null
  navigateToThread(tenantId, tenantName)
}
