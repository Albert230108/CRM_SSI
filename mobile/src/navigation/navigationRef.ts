import { CommonActions, createNavigationContainerRef } from '@react-navigation/native'

/**
 * A container-level navigation ref so non-React code (notification tap handlers) can navigate.
 * The nested target is App → Tenants tab → Thread; we dispatch a CommonActions.navigate so the
 * nested screen/params are resolved without the container ref's strict single-route typing.
 */
export const navigationRef = createNavigationContainerRef()

export function navigateToThread(tenantId: number, tenantName?: string): void {
  if (!navigationRef.isReady()) return
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
