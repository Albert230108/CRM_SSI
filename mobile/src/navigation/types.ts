/** Shared navigation param lists. The Thread route is reachable from both the Tenants tab
 *  (tenant list) and the Notifications tab (tapping a notification), so it appears in both — and
 *  so do the per-tenant info screens the chat header opens (Beds24 details, Notes, Brain). */

export type ThreadParams = { tenantId: number; tenantName?: string }
/** Per-tenant info screens opened from the chat header dropdown. */
export type TenantInfoParams = { tenantId: number; tenantName?: string }
export type EmailViewerParams = { subject?: string | null; html: string | null; text?: string }

/**
 * The Tenants and Notifications stacks expose an identical set of tenant routes (Thread + the three
 * info screens + EmailViewer), so ThreadScreen — typed against TenantsStackParamList — can navigate
 * to them from either stack.
 */
export type TenantsStackParamList = {
  TenantList: undefined
  Thread: ThreadParams
  BookingDetail: TenantInfoParams
  Notes: TenantInfoParams
  Brain: TenantInfoParams
  EmailViewer: EmailViewerParams
}

export type NotificationsStackParamList = {
  NotificationsList: undefined
  Thread: ThreadParams
  BookingDetail: TenantInfoParams
  Notes: TenantInfoParams
  Brain: TenantInfoParams
  EmailViewer: EmailViewerParams
}
