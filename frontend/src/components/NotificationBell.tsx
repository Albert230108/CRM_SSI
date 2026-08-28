import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatRelativeTime, getChannelIcon } from '../lib/timeFormat'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type NotificationItem = {
  id: number
  tenant_id: number | null
  tenant_name: string | null
  channel: string
  direction: string
  preview: string | null
  created_at: string
  event_at: string
  is_read: boolean
  thread_ref: string | null
}

export default function NotificationBell() {
  const navigate = useNavigate()
  const token = useAuthStore((state) => state.token)
  const [open, setOpen] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const [loading, setLoading] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined

  useEffect(() => {
    let cancelled = false

    const pollUnreadCount = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/notifications/unread-count`, { headers: authHeaders })
        if (!response.ok || cancelled) return
        const data: { count: number } = await response.json()
        setUnreadCount(data.count)
      } catch {
        // Ignore transient poll failures; next interval tick will retry.
      }
    }

    pollUnreadCount()
    const intervalId = window.setInterval(pollUnreadCount, 7000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const loadNotifications = async (nextFilter: 'all' | 'unread') => {
    try {
      setLoading(true)
      const params = new URLSearchParams({ limit: '10', unread_only: String(nextFilter === 'unread') })
      const response = await fetch(`${API_BASE_URL}/api/notifications?${params}`, { headers: authHeaders })
      if (!response.ok) return
      const data: NotificationItem[] = await response.json()
      setNotifications(data)
    } finally {
      setLoading(false)
    }
  }

  const handleToggleOpen = () => {
    setOpen((current) => {
      const next = !current
      if (next) void loadNotifications(filter)
      return next
    })
  }

  const handleFilterChange = (nextFilter: 'all' | 'unread') => {
    setFilter(nextFilter)
    void loadNotifications(nextFilter)
  }

  const handleMarkAllRead = async () => {
    await fetch(`${API_BASE_URL}/api/notifications/mark-all-read`, { method: 'POST', headers: authHeaders })
    setUnreadCount(0)
    void loadNotifications(filter)
  }

  const handleNotificationClick = async (notification: NotificationItem) => {
    if (!notification.is_read) {
      fetch(`${API_BASE_URL}/api/notifications/${notification.id}/mark-read`, { method: 'POST', headers: authHeaders }).catch(() => {})
      setUnreadCount((current) => Math.max(current - 1, 0))
      setNotifications((current) => current.map((item) => (item.id === notification.id ? { ...item, is_read: true } : item)))
    }
    setOpen(false)
    if (notification.tenant_id != null) {
      if (notification.thread_ref) {
        const params = new URLSearchParams({ channel: notification.channel, thread_ref: notification.thread_ref })
        navigate(`/dashboard/tenant/${notification.tenant_id}?${params}`)
      } else {
        navigate(`/dashboard/tenant/${notification.tenant_id}`)
      }
    }
  }

  const badgeLabel = unreadCount > 9 ? '9+' : String(unreadCount)

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={handleToggleOpen}
        aria-label="Notifications"
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-500 transition hover:bg-gray-50 hover:text-gray-900"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unreadCount > 0 ? (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold leading-none text-white">
            {badgeLabel}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="absolute right-0 top-full z-50 mt-2 w-96 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <span className="text-sm font-semibold text-gray-900">Notifications</span>
            <button type="button" onClick={handleMarkAllRead} className="text-xs font-medium text-cyan-700 transition hover:text-cyan-900">
              Mark all read
            </button>
          </div>
          <div className="flex gap-1 border-b border-gray-100 px-3 py-2">
            {(['all', 'unread'] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => handleFilterChange(option)}
                className={[
                  'rounded-lg px-2.5 py-1 text-xs font-medium transition',
                  filter === option ? 'bg-cyan-50 text-cyan-700' : 'text-gray-500 hover:bg-gray-50',
                ].join(' ')}
              >
                {option === 'all' ? 'All' : 'Unread'}
              </button>
            ))}
          </div>

          <div className="max-h-72 overflow-y-auto">
            {loading ? <p className="px-3 py-2 text-xs text-gray-500">Loading...</p> : null}
            {!loading && notifications.length === 0 ? (
              <p className="px-3 py-2 text-xs text-gray-400">No notifications yet.</p>
            ) : null}
            {notifications.map((notification) => (
              <button
                key={notification.id}
                type="button"
                onClick={() => handleNotificationClick(notification)}
                className={[
                  'block w-full border-b border-gray-50 px-3 py-2 text-left transition last:border-0 hover:bg-gray-50',
                  notification.is_read ? 'bg-white' : 'bg-cyan-50/40',
                ].join(' ')}
              >
                <div className="flex items-start gap-2">
                  <span className="mt-0.5">{getChannelIcon(notification.channel)}</span>
                  <div className="min-w-0 flex-1">
                    <p className="break-words text-sm font-medium text-gray-900">
                      {notification.channel.toLowerCase() === 'email' ? 'New email' : 'New WhatsApp message'}
                      {notification.tenant_name ? ` from ${notification.tenant_name}` : ''}
                    </p>
                    {notification.preview ? <p className="truncate text-xs text-gray-500">{notification.preview}</p> : null}
                    <p className="mt-0.5 text-[10px] text-gray-400">{formatRelativeTime(notification.event_at)}</p>
                  </div>
                  {!notification.is_read ? <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-cyan-500" /> : null}
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
