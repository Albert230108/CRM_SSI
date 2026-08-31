import { apiClient } from './client'

/**
 * Auth request functions mapped to the backend contract (`backend/app/api/auth.py`).
 *
 * These shapes mirror the Pydantic schemas in `backend/app/schemas/auth.py`. When the typed
 * OpenAPI client is generated (`npm run gen:api`, see package.json), swap these hand-written
 * types for the generated ones. Until then they are kept deliberately small and explicit.
 */

/** Matches `Token` (`backend/app/schemas/auth.py`). */
export type TokenResponse = {
  access_token: string
  token_type: string
}

/** Matches `CurrentUser` (`backend/app/schemas/auth.py`) — same fields the web AuthUser holds. */
export type CurrentUser = {
  id: number
  email: string
  full_name: string | null
  is_active: boolean
  is_admin: boolean
  whatsapp_notifications_enabled: boolean
  default_gmail_account_id: number | null
  default_whatsapp_account_id: string | null
}

/** POST /api/auth/login — no bearer required. */
export async function login(email: string, password: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/api/auth/login', { email, password })
  return data
}

/**
 * POST /api/auth/refresh — requires a still-valid bearer token (attached by the client
 * interceptor). Returns a fresh token. A 401 here means the session is already gone.
 */
export async function refresh(): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/api/auth/refresh')
  return data
}

/** GET /api/auth/me — the current user for the attached token. */
export async function me(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>('/api/auth/me')
  return data
}
