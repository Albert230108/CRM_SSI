import { Navigate, Route, Routes } from 'react-router-dom'
import { useEffect } from 'react'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Navbar from './components/Navbar'
import ProtectedRoute from './components/ProtectedRoute'
import SessionExpiredModal from './components/SessionExpiredModal'
import UnsavedNotesModal from './components/UnsavedNotesModal'
import Settings from './pages/Settings'
import AiTemplatesOverview from './pages/AiTemplatesOverview'
import AiTemplateEditor from './pages/AiTemplateEditor'
import AiTenantSettings from './pages/AiTenantSettings'
import AiAgentProfiles from './pages/AiAgentProfiles'
import AiAgentProfileEditor from './pages/AiAgentProfileEditor'
import AiAgentRuns from './pages/AiAgentRuns'
import AiAgentRunDetail from './pages/AiAgentRunDetail'
import RedoQaChat from './pages/RedoQaChat'
import BrainSections from './pages/BrainSections'
import AiPendingDrafts from './pages/AiPendingDrafts'
import ScheduledPlannerRuns from './pages/ScheduledPlannerRuns'
import AiPayloadPreview from './pages/AiPayloadPreview'
import Actions from './pages/Actions'
import WorkingMemoryHome from './pages/WorkingMemoryHome'
import AdminSettings from './pages/AdminSettings'
import InvitationSetup from './pages/InvitationSetup'
import PasswordReset from './pages/PasswordReset'
import { installInactivityLogout } from './lib/inactivityLogout'
import { installRefreshDiagnostics } from './lib/refreshDiagnostics'
import { useAuthStore } from './store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export default function App() {
  const token = useAuthStore((state) => state.token)
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  const setUser = useAuthStore((state) => state.setUser)
  const logout = useAuthStore((state) => state.logout)

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    fetch(`${API_BASE_URL}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async (response) => {
        // Only an actual auth rejection should end the session. A transient 5xx or a network
        // error must NOT log a valid user out (the previous `catch(() => logout())` did).
        if (response.status === 401 || response.status === 403) {
          logout()
          return
        }
        if (!response.ok) return
        setUser(await response.json())
      })
      .catch((error) => {
        // Aborted request (token change / unmount) or network failure: keep the session.
        if (error?.name !== 'AbortError') {
          console.warn('auth/me check failed; keeping existing session', error)
        }
      })
    return () => controller.abort()
  }, [token, setUser, logout])

  useEffect(() => {
    if (!isAuthenticated) return
    installRefreshDiagnostics()
    return installInactivityLogout()
  }, [isAuthenticated])

  return (
    <>
      <SessionExpiredModal />
      <UnsavedNotesModal />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/invite/:token" element={<InvitationSetup />} />
        <Route path="/invites/:token" element={<InvitationSetup />} />
        <Route path="/reset-password/:token" element={<PasswordReset />} />
        <Route
          path="/ai-runs/:runId"
          element={
            <ProtectedRoute>
              <AiAgentRunDetail />
            </ProtectedRoute>
          }
        />
        <Route
          path="/redo-requests/:redoLogId/chat"
          element={
            <ProtectedRoute>
              <RedoQaChat />
            </ProtectedRoute>
          }
        />
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <div className="flex h-screen flex-col overflow-hidden bg-gray-50">
                <Navbar />
                <div className="min-h-0 flex-1 overflow-auto">
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/dashboard/tenant/:tenantId" element={<Dashboard />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="/settings/ai-templates" element={<AiTemplatesOverview />} />
                    <Route path="/settings/ai-templates/:templateId" element={<AiTemplateEditor />} />
                    <Route path="/settings/ai-tenants" element={<AiTenantSettings />} />
                    <Route path="/settings/planner-schedules" element={<ScheduledPlannerRuns />} />
                    <Route path="/settings/brain" element={<BrainSections />} />
                    <Route path="/settings/ai-agents" element={<AiAgentProfiles />} />
                    <Route path="/settings/ai-agents/:profileId" element={<AiAgentProfileEditor />} />
                    <Route path="/ai-runs" element={<ProtectedRoute><AiAgentRuns /></ProtectedRoute>} />
                    <Route path="/ai-drafts" element={<AiPendingDrafts />} />
                    <Route path="/ai-payload-preview" element={<AiPayloadPreview />} />
                    <Route path="/actions" element={<Actions />} />
                    <Route path="/working-memory" element={<WorkingMemoryHome />} />
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
              </div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </>
  )
}
