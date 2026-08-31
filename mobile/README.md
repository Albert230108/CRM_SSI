# CRM SSI — Mobile (Expo / React Native)

Native Android client for CRM_SSI. See the full plan in
[`../docs/android-mobile-app-plan.md`](../docs/android-mobile-app-plan.md).

**Phase 0** (foundation) and **Phase 1** (MVP screens) are implemented:

- **Phase 0** — API client, auth/session store, navigation shell.
- **Phase 1** — tenant list (search), unified WhatsApp + email thread view (text-only) with a
  plain-text WhatsApp composer, and a notifications list with an unread tab badge. All server
  state runs through TanStack Query with foreground polling (paused when backgrounded).
- **Phase 2** — push notifications via the Expo Push service: on login the app registers its
  ExpoPushToken with the backend (`POST /api/devices/register`), taps deep-link into the tenant
  thread, and logout unregisters the token. The backend batches new-notification pushes (mirroring
  the WhatsApp debounce) and prunes stale tokens.

Rich HTML email rendering and email/rich composing remain deferred per the plan.

> **Push requires setup you own (see "Enable push" below):** a Firebase project wired into EAS for
> Android delivery. Until that's configured the client degrades gracefully — it simply doesn't
> obtain a token — and the rest of the app is unaffected.

### Phase 1 screens & data

| Screen | Source | Endpoint |
| --- | --- | --- |
| Tenant list + search | `src/screens/TenantListScreen.tsx` | `GET /api/tenants` |
| Thread (unified timeline) | `src/screens/ThreadScreen.tsx` | `GET /api/communications/tenants/{id}/grouped-thread` |
| WhatsApp send | composer in ThreadScreen | `POST /api/communications/tenants/{id}/send` |
| Notifications + badge | `src/screens/NotificationsScreen.tsx` | `GET /api/notifications`, `/unread-count` |

The unified thread flattens the backend's nested grouped-thread (email threads + interleaved
WhatsApp blocks + WhatsApp groups) into one chronological, de-duplicated bubble list
(`flattenThread` in `src/api/communications.ts`). WhatsApp sends always target an explicit
manual endpoint (CLAUDE.md invariant); when a tenant has more than one linked chat, the composer
shows a chip selector.

### Phase 2 push (client pieces)

| Piece | Source |
| --- | --- |
| Permission + ExpoPushToken | `src/lib/push.ts` |
| Register/unregister API | `src/api/devices.ts` |
| Lifecycle + tap deep-link | `src/hooks/usePushNotifications.ts`, `src/navigation/navigationRef.ts` |

Backend counterpart: `backend/app/api/devices.py`, `backend/app/services/push_notification_service.py`,
model `device_tokens`, and migration `0087_add_device_tokens_and_push`.

## Enable push (you own this)

Push delivery needs a Firebase project for Android, wired into EAS:

1. Create a Firebase project and add an Android app with package `com.ssi.crm`; download
   `google-services.json`.
2. Upload the FCM **V1** service-account key to Expo:
   `npx eas-cli credentials` (Android → push key).
3. Ensure the EAS `projectId` is set (`npx eas-cli init` writes it into `app.json → extra.eas`);
   the client only requests a token when a `projectId` is present.
4. Build a dev/preview APK (not Expo Go) and log in — the device registers automatically.

Optional backend env vars (all have safe defaults; see `push_notification_service.py`):
`EXPO_PUSH_API_URL`, `EXPO_ACCESS_TOKEN`, `PUSH_NOTIFICATION_DEBOUNCE_SECONDS`.

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
