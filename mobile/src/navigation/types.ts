/** Shared navigation param lists. The Thread route is reachable from both the Tenants tab
 *  (tenant list) and the Notifications tab (tapping a notification), so it appears in both. */

export type ThreadParams = { tenantId: number; tenantName?: string }
export type TenantDetailParams = { tenantId: number; tenantName?: string }
export type EmailViewerParams = { subject?: string | null; html: string | null; text?: string }

export type TenantsStackParamList = {
  TenantList: undefined
  TenantDetail: TenantDetailParams
  Thread: ThreadParams
  EmailViewer: EmailViewerParams
}

export type NotificationsStackParamList = {
  NotificationsList: undefined
  Thread: ThreadParams
  EmailViewer: EmailViewerParams
}
