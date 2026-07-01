import { useAuthStore } from '../store/authStore'
import crmLogo from '../assets/logo.jpg'

export default function Navbar() {
  const userEmail = useAuthStore((state) => state.userEmail)
  const logout = useAuthStore((state) => state.logout)

  return (
    <header className="w-full border-b border-gray-200 bg-white backdrop-blur">
      <div className="flex w-full items-center justify-between px-6 py-4">
        <div className="flex items-center gap-3">
          {/* <img src={import.meta.env.VITE_LOGO_URL} alt="CRM logo" className="h-8 w-auto" /> */}
          <img src={crmLogo} alt="CRM logo" className="h-8 w-auto" />
          <h1 className="text-base font-semibold text-gray-900">CRM SSI</h1>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">{userEmail ?? 'Signed in'}</span>
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
