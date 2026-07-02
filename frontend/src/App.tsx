import { Navigate, Route, Routes } from 'react-router-dom'
import { useEffect } from 'react'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Navbar from './components/Navbar'
import ProtectedRoute from './components/ProtectedRoute'
import Settings from './pages/Settings'
import AdminSettings from './pages/AdminSettings'
import InvitationSetup from './pages/InvitationSetup'
import PasswordReset from './pages/PasswordReset'
import { useAuthStore } from './store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export default function App() {
  const token = useAuthStore((state) => state.token)
  const setUser = useAuthStore((state) => state.setUser)
  const logout = useAuthStore((state) => state.logout)

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    fetch(`${API_BASE_URL}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('Unauthorized')
        return response.json()
      })
      .then((data) => setUser(data))
      .catch(() => logout())
    return () => controller.abort()
  }, [token, setUser, logout])

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/invite/:token" element={<InvitationSetup />} />
      <Route path="/reset-password/:token" element={<PasswordReset />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <div className="min-h-screen bg-gray-50">
              <Navbar />
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/dashboard/tenant/:tenantId" element={<Dashboard />} />
                <Route path="/settings" element={<Settings />} />
                <Route
                  path="/admin/settings"
                  element={
                    <ProtectedRoute adminOnly>
                      <AdminSettings />
                    </ProtectedRoute>
                  }
                />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </div>
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}
