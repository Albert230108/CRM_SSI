const TOKEN_STORAGE_KEY = 'quotation_manager_token'
const API_BASE_URL = import.meta.env.VITE_QUOTATION_API_BASE_URL ?? ''

/**
 * Reads the ?token= query param handed off by the CRM, stashes it in
 * sessionStorage (survives navigation within this tab, cleared when the tab
 * closes), and strips it from the visible URL so it doesn't linger in the
 * address bar or get accidentally shared.
 */
export function initToken(): string | null {
  const url = new URL(window.location.href)
  const tokenFromUrl = url.searchParams.get('token')
  if (tokenFromUrl) {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, tokenFromUrl)
    url.searchParams.delete('token')
    window.history.replaceState({}, '', url.toString())
  }
  return sessionStorage.getItem(TOKEN_STORAGE_KEY)
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_STORAGE_KEY)
}

export interface QuotationTokenClaims {
  tenant_id: number
  booking_id: string | null
}

/**
 * Decodes the (unverified) JWT payload purely to read tenant_id/booking_id
 * for prefill/routing. Real authorization always happens on the backend,
 * which verifies the signature - this is display convenience only.
 */
export function decodeTokenClaims(token: string): QuotationTokenClaims | null {
  try {
    const [, payloadSegment] = token.split('.')
    const json = atob(payloadSegment.replace(/-/g, '+').replace(/_/g, '/'))
    const payload = JSON.parse(json)
    return { tenant_id: payload.tenant_id, booking_id: payload.booking_id ?? null }
  } catch {
    return null
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers = new Headers(options.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body) headers.set('Content-Type', 'application/json')

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  if (!response.ok) {
    const detail = await response.text()
    throw new ApiError(response.status, detail || response.statusText)
  }
  return (await response.json()) as T
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET' })
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) })
}
