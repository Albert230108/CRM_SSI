import { useAuthStore } from '../store/authStore'

export default function SessionExpiredModal() {
  const sessionExpired = useAuthStore((state) => state.sessionExpired)
  const logout = useAuthStore((state) => state.logout)

  if (!sessionExpired) return null

  return (
    <div
      role="alertdialog"
      aria-live="assertive"
      aria-label="Session expired"
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-4 bg-white/60 backdrop-blur-md"
    >
      <div className="flex w-full max-w-sm flex-col items-center gap-2 rounded-xl bg-white p-4 text-center shadow-xl">
        <p className="text-lg font-semibold text-gray-800">Your session has expired</p>
        <p className="text-sm text-gray-500">Please sign in again to continue.</p>
        <button
          type="button"
          onClick={logout}
          className="w-full rounded-xl bg-cyan-600 px-4 py-2.5 font-semibold text-white transition hover:bg-cyan-700"
        >
          Sign in again
        </button>
      </div>
    </div>
  )
}
