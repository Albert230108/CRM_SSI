/** Shared navigation param lists. The Thread route is reachable from both the Tenants tab
 *  (tenant list) and the Notifications tab (tapping a notification), so it appears in both. */

export type ThreadParams = { tenantId: number; tenantName?: string }

export type TenantsStackParamList = {
  TenantList: undefined
  Thread: ThreadParams
}

export type NotificationsStackParamList = {
  NotificationsList: undefined
  Thread: ThreadParams
}
