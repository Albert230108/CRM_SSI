import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import NotificationBell from './NotificationBell'
import { useAuthStore } from '../store/authStore'
import crmLogo from '../assets/logo.jpg'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export default function Navbar() {
  const location = useLocation()
  const user = useAuthStore((state) => state.user)
  const token = useAuthStore((state) => state.token)
  const logout = useAuthStore((state) => state.logout)
  const settingsActive = location.pathname.startsWith('/settings')
  const adminActive = location.pathname.startsWith('/admin')
  const aiDraftsActive = location.pathname.startsWith('/ai-drafts')
  const [pendingAiDraftsCount, setPendingAiDraftsCount] = useState(0)

  useEffect(() => {
    if (!token) return
    let cancelled = false

    const pollPendingAiDrafts = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/ai-auto-drafts`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!response.ok || cancelled) return
        const data: unknown[] = await response.json()
        setPendingAiDraftsCount(data.length)
      } catch {
        // Ignore transient poll failures; next interval tick will retry.
      }
    }

    pollPendingAiDrafts()
    const intervalId = window.setInterval(pollPendingAiDrafts, 15000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [token])

  const aiDraftsBadgeLabel = pendingAiDraftsCount > 9 ? '9+' : String(pendingAiDraftsCount)

  return (
    <header className="relative z-50 w-full border-b border-gray-200 bg-white backdrop-blur">
      <div className="flex w-full items-center justify-between px-6 py-4">
        <Link to="/" className="flex items-center gap-3">
          <img src={crmLogo} alt="CRM logo" className="h-8 w-auto" />
          <h1 className="text-base font-semibold text-gray-900 transition hover:text-gray-700">CRM SSI</h1>
        </Link>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">{user?.full_name || user?.email || 'Signed in'}</span>
          <NotificationBell />
          {user?.is_admin ? (
            <Link
              to="/admin/settings"
              className={`inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${adminActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
            >
              <span>Admin Settings</span>
            </Link>
          ) : null}
          <Link
            to="/ai-drafts"
            className={`relative inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${aiDraftsActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
          >
            <span>AI Drafts</span>
            {pendingAiDraftsCount > 0 ? (
              <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold leading-none text-white">
                {aiDraftsBadgeLabel}
              </span>
            ) : null}
          </Link>
          <Link
            to="/settings"
            className={`inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${settingsActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
          >
            <span>Settings</span>
          </Link>
          <button
            onClick={logout}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50"
          >
            Logout
          </button>
        </div>
      </div>
    </header>
  )
}
