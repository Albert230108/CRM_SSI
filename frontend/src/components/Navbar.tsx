import { useAuthStore } from '../store/authStore'

export default function Navbar() {
  const userEmail = useAuthStore((state) => state.userEmail)
  const logout = useAuthStore((state) => state.logout)

  return (
    <header className="border-b border-gray-200 bg-white backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-cyan-600">CRM</p>
          <h1 className="text-lg font-semibold text-gray-900">Operations Dashboard</h1>
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
