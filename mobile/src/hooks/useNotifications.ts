import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '../api/notifications'

export const notificationKeys = {
  list: ['notifications'] as const,
  unreadCount: ['unread-count'] as const,
}

/** Notifications list, polled in the foreground. */
export function useNotifications() {
  return useQuery({
    queryKey: notificationKeys.list,
    queryFn: listNotifications,
    refetchInterval: 15_000,
  })
}

/** Unread count for the tab badge, polled more frequently. */
export function useUnreadCount() {
  return useQuery({
    queryKey: notificationKeys.unreadCount,
    queryFn: getUnreadCount,
    refetchInterval: 15_000,
  })
}

function useInvalidateNotifications() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: notificationKeys.list })
    void queryClient.invalidateQueries({ queryKey: notificationKeys.unreadCount })
  }
}

export function useMarkNotificationRead() {
  const invalidate = useInvalidateNotifications()
  return useMutation({
    mutationFn: (notificationId: number) => markNotificationRead(notificationId),
    onSuccess: invalidate,
  })
}

export function useMarkAllNotificationsRead() {
  const invalidate = useInvalidateNotifications()
  return useMutation({
    mutationFn: () => markAllNotificationsRead(),
    onSuccess: invalidate,
  })
}
