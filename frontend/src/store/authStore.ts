import { create } from 'zustand'

export type AuthUser = {
  id: number
  email: string
  full_name: string | null
  is_active: boolean
  is_admin: boolean
} | null

type AuthState = {
  token: string | null
  user: AuthUser
  isAuthenticated: boolean
  setAuth: (token: string, user?: AuthUser) => void
  setUser: (user: AuthUser) => void
  logout: () => void
}

const tokenKey = 'crm_auth_token'

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(tokenKey),
  user: null,
  isAuthenticated: Boolean(localStorage.getItem(tokenKey)),
  setAuth: (token, user = null) => {
    localStorage.setItem(tokenKey, token)
    set({ token, user, isAuthenticated: true })
  },
  setUser: (user) => set({ user }),
  logout: () => {
    localStorage.removeItem(tokenKey)
    set({ token: null, user: null, isAuthenticated: false })
  },
}))
