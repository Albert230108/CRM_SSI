import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import crmLogo from '../assets/logo.jpg'

export default function Navbar() {
  const location = useLocation()
  const userEmail = useAuthStore((state) => state.userEmail)
  const logout = useAuthStore((state) => state.logout)
  const settingsActive = location.pathname === '/settings'

  return (
    <header className="w-full border-b border-gray-200 bg-white backdrop-blur">
      <div className="flex w-full items-center justify-between px-6 py-4">
        <Link to="/" className="flex items-center gap-3">
          {/* <img src={import.meta.env.VITE_LOGO_URL} alt="CRM logo" className="h-8 w-auto" /> */}
          <img src={crmLogo} alt="CRM logo" className="h-8 w-auto" />
          <h1 className="text-base font-semibold text-gray-900 transition hover:text-gray-700">CRM SSI</h1>
        </Link>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">{userEmail ?? 'Signed in'}</span>
          <Link
            to="/settings"
            className={`inline-flex items-center gap-1.5 text-sm transition hover:text-gray-900 ${settingsActive ? 'font-medium text-gray-900' : 'text-gray-500'}`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
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
