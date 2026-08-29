import { Navigate, Route, Routes } from 'react-router-dom'
import { lazy, Suspense, useEffect } from 'react'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Navbar from './components/Navbar'
import ProtectedRoute from './components/ProtectedRoute'
import SessionExpiredModal from './components/SessionExpiredModal'
import UnsavedNotesModal from './components/UnsavedNotesModal'
import InlineSpinner from './components/InlineSpinner'
// Core CRM (Dashboard) loads eagerly; the heavier off-Core routes (AI subsystem,
// settings, admin, auth flows) are code-split so they don't inflate the initial bundle.
const Settings = lazy(() => import('./pages/Settings'))
const AiTemplatesOverview = lazy(() => import('./pages/AiTemplatesOverview'))
const AiTemplateEditor = lazy(() => import('./pages/AiTemplateEditor'))
const AiTenantSettings = lazy(() => import('./pages/AiTenantSettings'))
const AiAgentProfiles = lazy(() => import('./pages/AiAgentProfiles'))
const AiAgentProfileEditor = lazy(() => import('./pages/AiAgentProfileEditor'))
const AiAgentRuns = lazy(() => import('./pages/AiAgentRuns'))
const AiAgentRunDetail = lazy(() => import('./pages/AiAgentRunDetail'))
const RedoQaChat = lazy(() => import('./pages/RedoQaChat'))
const BrainSections = lazy(() => import('./pages/BrainSections'))
const AiPendingDrafts = lazy(() => import('./pages/AiPendingDrafts'))
const ScheduledPlannerRuns = lazy(() => import('./pages/ScheduledPlannerRuns'))
const AiPayloadPreview = lazy(() => import('./pages/AiPayloadPreview'))
const Actions = lazy(() => import('./pages/Actions'))
const WorkingMemoryHome = lazy(() => import('./pages/WorkingMemoryHome'))
const AdminSettings = lazy(() => import('./pages/AdminSettings'))
const InvitationSetup = lazy(() => import('./pages/InvitationSetup'))
const PasswordReset = lazy(() => import('./pages/PasswordReset'))
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
      <Suspense
        fallback={
          <div className="flex h-screen items-center justify-center bg-gray-50">
            <InlineSpinner size="lg" className="text-brand-600" />
          </div>
        }
      >
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
      </Suspense>
    </>
  )
}
