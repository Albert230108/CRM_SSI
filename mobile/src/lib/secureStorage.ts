import * as SecureStore from 'expo-secure-store'

/**
 * Thin wrapper over expo-secure-store for the JWT — the RN replacement for the web app's
 * `localStorage` key `crm_auth_token` (`frontend/src/store/authStore.ts`). SecureStore keeps
 * the token in the platform keystore (Android Keychain/Keystore) rather than plain storage.
 *
 * SecureStore keys must match [A-Za-z0-9._-], so we keep an underscore form of the web key.
 */
const TOKEN_KEY = 'crm_auth_token'

export async function getStoredToken(): Promise<string | null> {
  return SecureStore.getItemAsync(TOKEN_KEY)
}

export async function setStoredToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token)
}

export async function clearStoredToken(): Promise<void> {
  await SecureStore.deleteItemAsync(TOKEN_KEY)
}
