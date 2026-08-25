import { create } from 'zustand'

export type AuthUser = {
  id: number
  email: string
  full_name: string | null
  is_active: boolean
  is_admin: boolean
  whatsapp_notifications_enabled: boolean
  default_gmail_account_id: number | null
  default_whatsapp_account_id: string | null
} | null

type AuthState = {
  token: string | null
  user: AuthUser
  isAuthenticated: boolean
  sessionExpired: boolean
  setAuth: (token: string, user?: AuthUser) => void
  setUser: (user: AuthUser) => void
  logout: () => void
  flagSessionExpired: () => void
}

const tokenKey = 'crm_auth_token'

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(tokenKey),
  user: null,
  isAuthenticated: Boolean(localStorage.getItem(tokenKey)),
  sessionExpired: false,
  setAuth: (token, user = null) => {
    localStorage.setItem(tokenKey, token)
    set({ token, user, isAuthenticated: true, sessionExpired: false })
  },
  setUser: (user) => set({ user }),
  logout: () => {
    localStorage.removeItem(tokenKey)
    set({ token: null, user: null, isAuthenticated: false, sessionExpired: false })
  },
  // Only surfaces the prompt while a session is actually active, so a 401 racing
  // in after an explicit logout (or on the public login page) doesn't retrigger it.
  flagSessionExpired: () =>
    set((state) => (state.isAuthenticated ? { sessionExpired: true } : state)),
}))
