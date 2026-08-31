import { apiClient } from './client'

/**
 * Device push-token endpoints (`backend/app/api/devices.py`, mounted under /api). Both require a
 * valid bearer token, which the client interceptor attaches. Unregister must therefore be called
 * while still authenticated (before logout clears the JWT).
 */

/** POST /api/devices/register — upsert this device's Expo push token for the current user. */
export async function registerDevice(token: string, platform: string): Promise<void> {
  await apiClient.post('/api/devices/register', { token, platform })
}

/** POST /api/devices/unregister — remove this device's token (on logout). */
export async function unregisterDevice(token: string): Promise<void> {
  await apiClient.post('/api/devices/unregister', { token })
}
