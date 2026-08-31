import { apiClient } from './client'

/**
 * Notification endpoints (`backend/app/api/notifications.py`, router prefix /notifications,
 * mounted under /api). Types mirror `NotificationRead` / `UnreadCountRead`.
 */
export type NotificationRead = {
  id: number
  tenant_id: number | null
  tenant_name: string | null
  channel: string
  direction: string
  preview: string | null
  thread_ref: string | null
  created_at: string
  event_at: string
  is_read: boolean
}

/** GET /api/notifications */
export async function listNotifications(): Promise<NotificationRead[]> {
  const { data } = await apiClient.get<NotificationRead[]>('/api/notifications')
  return data
}

/** GET /api/notifications/unread-count */
export async function getUnreadCount(): Promise<number> {
  const { data } = await apiClient.get<{ count: number }>('/api/notifications/unread-count')
  return data.count
}

/** POST /api/notifications/{id}/mark-read */
export async function markNotificationRead(notificationId: number): Promise<NotificationRead> {
  const { data } = await apiClient.post<NotificationRead>(
    `/api/notifications/${notificationId}/mark-read`,
  )
  return data
}

/** POST /api/notifications/mark-all-read → number marked. */
export async function markAllNotificationsRead(): Promise<number> {
  const { data } = await apiClient.post<{ marked: number }>('/api/notifications/mark-all-read')
  return data.marked
}
