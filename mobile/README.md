# CRM SSI — Mobile (Expo / React Native)

Native Android client for CRM_SSI. See the full plan in
[`../docs/android-mobile-app-plan.md`](../docs/android-mobile-app-plan.md).

This is the **Phase 0 foundation**: API client, auth/session store, and the navigation shell.
Real feature screens (tenant list, thread view, notifications) arrive in Phase 1; push in Phase 2.

## Stack

- Expo SDK 57 (managed) + React Native + TypeScript
- React Navigation (native-stack + bottom-tabs)
- TanStack Query (server state) — polling intervals wired per-query in Phase 1
- Zustand (auth/session state)
- expo-secure-store (JWT storage)
- axios (single API client)

## Configuration

The backend base URL comes from `EXPO_PUBLIC_API_BASE_URL` (see `.env` / `.env.example`).
It is a **public** value inlined into the bundle — never put secrets in `EXPO_PUBLIC_*`.
Falls back to `https://ssi-crm.theworkpc.com` when unset (`src/config.ts`).

## Architecture (Phase 0)

```
src/
  config.ts              # base URL + token-refresh interval
  api/
    sessionBridge.ts     # decouples the client from the store (avoids a require cycle)
    client.ts            # axios: Bearer request interceptor + 401 -> logout response interceptor
    auth.ts              # login / refresh / me request fns (typed to backend/app/schemas/auth.py)
  lib/
    secureStorage.ts     # SecureStore wrapper for the JWT (web app used localStorage 'crm_auth_token')
    session.ts           # proactive token refresh (interval + AppState), mirrors inactivityLogout.ts
  store/
    authStore.ts         # Zustand: hydrate / login / logout; wires the bridge + session controller
  navigation/
    RootNavigator.tsx    # loading splash -> auth stack (Login) vs app tabs, by auth status
    AppTabs.tsx          # bottom tabs: Dashboard, Notifications, Settings
  screens/
    LoginScreen.tsx      # minimal functional login (polish in Phase 1)
    SettingsScreen.tsx   # signed-in user + logout
    PlaceholderScreen.tsx# Dashboard/Notifications placeholders
App.tsx                  # providers (Query, SafeArea) + hydrate on launch
```

### Session model (plan decision (a): accept re-logins)

The backend issues one 120-min access token and has **no refresh token**; `/api/auth/refresh`
only works while the current token is still valid. So:

- **Proactive refresh** (`src/lib/session.ts`) tops up the token before expiry while the app is
  foregrounded (interval + on return-to-foreground).
- **A 401 on a bearer request** (`src/api/client.ts`) clears the session and routes to Login —
  we do **not** attempt refresh on a 401 (it would also 401). A phone backgrounded past 120 min
  therefore requires a fresh login. This is the accepted trade-off; a real refresh-token backend
  is the deferred fallback (plan decision (b)).

## Develop

```bash
cd mobile
npm install
npm start          # Expo dev server (press 'a' for Android)
npm run typecheck  # tsc --noEmit
```

> Native FCM (Phase 2) requires an EAS **dev build**, not Expo Go.

## Generate API types (optional)

`openapi-typescript` is not a tracked dependency (it peers on TS 5, repo uses TS 6). Run on demand:

```bash
npm run gen:api    # writes src/types/api.d.ts from the live /openapi.json
```

Then replace the hand-written types in `src/api/auth.ts` with the generated ones.

## Build a preview APK (sideloadable)

Requires an Expo account and the EAS CLI login (done by you, not in-repo):

```bash
npx eas-cli login
npx eas-cli build -p android --profile preview
```

The `preview` profile (`eas.json`) produces an internal-distribution **APK** for sideloading.
