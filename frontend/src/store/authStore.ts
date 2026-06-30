import { create } from 'zustand'

type AuthState = {
  token: string | null
  userEmail: string | null
  isAuthenticated: boolean
  setAuth: (token: string, userEmail?: string | null) => void
  logout: () => void
}

const tokenKey = 'crm_auth_token'
const emailKey = 'crm_auth_email'

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(tokenKey),
  userEmail: localStorage.getItem(emailKey),
  isAuthenticated: Boolean(localStorage.getItem(tokenKey)),
  setAuth: (token, userEmail = null) => {
    localStorage.setItem(tokenKey, token)
    if (userEmail) {
      localStorage.setItem(emailKey, userEmail)
    } else {
      localStorage.removeItem(emailKey)
    }
    set({ token, userEmail, isAuthenticated: true })
  },
  logout: () => {
    localStorage.removeItem(tokenKey)
    localStorage.removeItem(emailKey)
    set({ token: null, userEmail: null, isAuthenticated: false })
  },
}))
