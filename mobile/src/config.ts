/**
 * App configuration. The API base URL comes from an EXPO_PUBLIC_ env var so it can differ
 * per build (dev vs. preview vs. prod) without code changes. EXPO_PUBLIC_ vars are inlined
 * into the bundle at build time, so this must NOT hold secrets — the CRM base URL is public.
 *
 * See docs/android-mobile-app-plan.md (Phase 0). The server already lives at
 * https://ssi-crm.theworkpc.com/api.
 */

const DEFAULT_API_BASE_URL = 'https://ssi-crm.theworkpc.com'

// Trailing slashes are stripped so callers can safely build `${API_BASE_URL}/api/...`.
export const API_BASE_URL = (
  process.env.EXPO_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL
).replace(/\/+$/, '')

/**
 * How often to proactively refresh the access token while the app is foregrounded.
 *
 * The backend issues a single 120-min access token and has NO refresh token
 * (`backend/app/core/security.py` ACCESS_TOKEN_EXPIRE_MINUTES = 120, `/api/auth/refresh`
 * requires a still-valid token). So we mirror the web app: refresh proactively before expiry
 * rather than trying to recover on a 401. 50 min keeps a foregrounded session comfortably
 * alive under the 120-min cap.
 */
export const TOKEN_REFRESH_INTERVAL_MS = 50 * 60 * 1000

/** Network request timeout for API calls. */
export const REQUEST_TIMEOUT_MS = 20_000
