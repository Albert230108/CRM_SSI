import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'

import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '../config'
import { sessionBridge } from './sessionBridge'

/**
 * The single API client for the whole app — the RN replacement for the web app's
 * per-call `fetch()` plus the `window.fetch` monkey-patch (`frontend/src/lib/sessionExpiry.ts`).
 *
 * Request interceptor: attach `Authorization: Bearer <token>` when a token exists.
 * Response interceptor: a 401 on a bearer request means the session is dead. We do NOT try
 * `/api/auth/refresh` here — that endpoint requires a still-valid token, so on a 401 it would
 * also 401. Instead we hand off to the auth store (via sessionBridge) to clear state and route
 * to Login. Token longevity is maintained proactively elsewhere (see src/lib/session.ts).
 */
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: { Accept: 'application/json' },
})

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = sessionBridge.getToken()
  if (token) {
    // Normalise to AxiosHeaders so `.set` is always available regardless of how the caller
    // passed headers in.
    const headers = AxiosHeaders.from(config.headers)
    headers.set('Authorization', `Bearer ${token}`)
    config.headers = headers
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status
    const sentBearer = Boolean(
      AxiosHeaders.from(error.config?.headers).get('Authorization'),
    )
    if (status === 401 && sentBearer) {
      sessionBridge.handleUnauthorized()
    }
    return Promise.reject(error)
  },
)
