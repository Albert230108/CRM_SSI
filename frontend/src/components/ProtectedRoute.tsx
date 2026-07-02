import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

type ProtectedRouteProps = {
  children: React.ReactNode
  adminOnly?: boolean
}

export default function ProtectedRoute({ children, adminOnly = false }: ProtectedRouteProps) {
  const user = useAuthStore((state) => state.user)
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (adminOnly && user === null) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-gray-500">Loading...</div>
  }

  if (adminOnly && !user?.is_admin) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}
