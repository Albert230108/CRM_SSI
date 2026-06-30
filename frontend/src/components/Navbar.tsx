import { useAuthStore } from '../store/authStore'

export default function Navbar() {
  const userEmail = useAuthStore((state) => state.userEmail)
  const logout = useAuthStore((state) => state.logout)

  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-cyan-400">CRM</p>
          <h1 className="text-lg font-semibold text-white">Operations Dashboard</h1>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-slate-300">{userEmail ?? 'Signed in'}</span>
          <button
            onClick={logout}
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm font-medium text-white transition hover:border-slate-500 hover:bg-slate-800"
          >
            Logout
          </button>
        </div>
      </div>
    </header>
  )
}
