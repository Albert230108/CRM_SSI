# Plan: Native Android (APK) Mobile App for CRM_SSI

> **Revision note (2026-08-31):** Three edits applied after validating the original plan
> against the codebase. Changed sections are marked **[EDITED]**. The edits are:
> 1. Phase 0 auth uses **proactive refresh + 401→login**, not "refresh-on-401" (which
>    cannot work — `/auth/refresh` requires a still-valid token; there are no refresh tokens).
> 2. An explicit **token-lifetime decision** (accept re-logins vs. add backend refresh
>    tokens) is called out; Phase 1 is no longer described as strictly "no backend change."
> 3. Phase 2 FCM hooks the single `create_notification()` choke point for the in-app bell;
>    the AI-draft staff ping (`notify_admins_of_new_draft`) is a **separate, optional** hook
>    that does **not** write `Notification` rows.

## Context

Today CRM_SSI ships only a desktop-oriented React web SPA (`frontend/`, ~28k LOC) served
same-origin behind nginx. The goal is a downloadable Android APK that connects to the
existing server. The chosen approach is a full React Native rewrite (not a WebView wrapper)
plus native push via Firebase Cloud Messaging (FCM).

The good news from exploration: the server is already mobile-ready and needs almost no change
to be *connectable*. The cost is almost entirely on the client (a new RN app) plus a focused
backend addition for push — and, depending on the token-lifetime decision below, a small
optional backend addition for session longevity.

## What already works in our favor

* Clean JSON REST API under `https://ssi-crm.theworkpc.com/api/...`, OpenAPI at `/openapi.json`.
* Stateless JWT bearer auth, no cookies: `POST /api/auth/login` with JSON `{email,password}` →
  `{access_token, token_type:"bearer"}` (`backend/app/api/auth.py:16`). Validated via
  `Authorization: Bearer` (`backend/app/core/dependencies.py`). Refresh at
  `POST /api/auth/refresh`, `GET /api/auth/me`. Token expiry is 120 min
  (`backend/app/core/security.py:13`).
* CORS is a non-issue for a native client (RN uses native HTTP, not a browser) — no backend
  CORS change required for the app itself.
* Public HTTPS with a valid Let's Encrypt cert → standard TLS, no cert-pinning workarounds needed.

### Auth model — important constraints **[EDITED]**

Understanding the exact auth model matters because it drives the Phase 0 client design:

* There is **one short-lived access token (120 min)** and **no refresh token**.
* `POST /api/auth/refresh` depends on `get_current_user` (`backend/app/core/dependencies.py:21`),
  so **it only works while the current token is still valid**. It re-issues a fresh 120-min
  token from a valid one. It **cannot** revive an already-expired token.
* The web app therefore refreshes **proactively every 5 minutes while the user is active**,
  before expiry (`frontend/src/lib/inactivityLogout.ts:20`). On an actual `401` it does **not**
  try to recover — it flags the session expired and forces re-login
  (`frontend/src/lib/sessionExpiry.ts:24`).

**Consequence for mobile:** a 120-min hard cap with no refresh token means a phone that is
backgrounded past the token lifetime comes back logged out (proactive refresh only runs while
the app is foregrounded). See the token-lifetime decision under Phase 0.

## What does NOT port and must be rebuilt

Everything visual/interactive is HTML + Tailwind + DOM and will be rewritten in RN primitives:

* Router: `react-router-dom` (`BrowserRouter` in `frontend/src/main.tsx`; `Routes`/`Route` in
  `frontend/src/App.tsx`) → React Navigation.
* Token storage: `localStorage` key `crm_auth_token` in `frontend/src/store/authStore.ts` →
  Expo SecureStore / encrypted storage (no `localStorage` in RN). Note the stored user also
  carries `default_gmail_account_id`, `default_whatsapp_account_id`, and
  `whatsapp_notifications_enabled`, which drive defaults — keep them in the RN auth store.
* The global `window.fetch` monkey-patch for 401 detection (`frontend/src/lib/sessionExpiry.ts`)
  and inactivity/proactive refresh (`frontend/src/lib/inactivityLogout.ts`) → a proper
  Axios/fetch interceptor + refresh timer in the RN API client.
* Core UI: `ThreadView.tsx` (3,116 lines), `TenantList.tsx`, contentEditable rich composers
  (`RichMessageComposer`, `AiChatComposer`), `sanitizeHtml`, drag/resize canvases
  (`WorkingMemoryCanvas`, `AiTemplateSectionCanvas`, `useDraggablePosition`, `useResizableSize`),
  right-click `TenantContextMenu`, and `overflow-x-auto` tables.
* Desktop-only features that will be dropped or degraded on mobile: File System Access API /
  OneDrive directory picker (`OneDriveBox.tsx`, `fileHandleStore.ts`) — already feature-detected
  as unsupported off-Chromium.
* `setInterval` polling everywhere (Navbar 15s/2s, NotificationBell 7s, ThreadView 7s/2s/1.5s,
  etc.) → foreground React Query polling + FCM push for background/closed-app alerts.

## Scope decision & recommendation

A 1:1 native rebuild of all ~19 pages (AdminSettings 67KB, Actions 59KB, the AI-agent editors,
drag/resize canvases) is a multi-month effort and much of it is desktop-only tooling that makes
little sense on a phone. Recommendation: build a focused, phased mobile app covering the
high-value on-the-go workflows first, not a total feature-parity port. The plan below is phased
so a usable APK ships early and scope grows deliberately.

## Recommended stack

* Expo (managed workflow) + React Native + TypeScript — gives EAS Build for reproducible APKs
  without local Android SDK wrangling. **Note:** native FCM (`@react-native-firebase/messaging`)
  requires an EAS **dev build** with its config plugin — it does **not** run in Expo Go, so plan
  to test push on a dev/preview build, not Expo Go.
* React Navigation (native-stack + bottom-tabs) for routing.
* TanStack Query (React Query) for all server state, caching, and polling — replaces the ad-hoc
  `fetch` + `setInterval` pattern with one client.
* Zustand for auth/session state (already the web app's choice — logic ports even though storage
  does not).
* expo-secure-store for the JWT.
* A generated or hand-written typed API client from `/openapi.json` (e.g. `openapi-typescript`)
  so request/response types match the Pydantic schemas.

## Phased implementation

### Phase 0 — Foundations (new `mobile/` app)

* Scaffold `mobile/` as an Expo TS project (kept separate from `frontend/`; shares nothing at
  runtime, but copy domain types from `backend/app/schemas` via the OpenAPI generator).

* **Central API client [EDITED]:** a single Axios/fetch instance with base URL from an app config
  (`EXPO_PUBLIC_API_BASE_URL=https://ssi-crm.theworkpc.com`) and a request interceptor that
  injects `Authorization: Bearer`. Session handling mirrors the web app rather than the original
  "refresh-on-401" idea, which cannot work against this backend:
  * **Proactive refresh:** a timer calls `POST /api/auth/refresh` on an interval while the app is
    foregrounded and the token is still valid, swapping in the new token — the RN equivalent of
    `inactivityLogout.ts`. Re-arm it on app foreground (`AppState` change) so a returning app
    refreshes immediately if the token is still alive.
  * **401 handling:** a response interceptor treats any `401` on a Bearer request as a dead
    session → clear token and route to Login (the RN equivalent of `sessionExpiry.ts`). Do **not**
    attempt `/auth/refresh` on a 401 — the token is already invalid and refresh will also 401.

* **Token-lifetime decision — DECIDED: (a) accept re-logins, no backend change [EDITED]:** with a
  120-min token and no refresh token, a backgrounded phone past that window forces a re-login. The
  chosen approach is **(a)**: proactive refresh keeps active sessions alive, and a long background
  gap simply means logging in again. This keeps Phase 1 backend-free and ships the MVP fastest. No
  refresh-token infrastructure is built for now.
  * **Fallback for later — (b) add a real refresh-token mechanism to the backend.** Longer-lived,
    revocable refresh tokens so the app can silently re-auth after a long background. This is a
    **net-new backend change** (model + endpoints + issuance/rotation/revocation). Deferred; revisit
    only if re-login frequency proves annoying in real use.

* **Auth store (Zustand) backed by `expo-secure-store`:** `login()` → POST `/api/auth/login`;
  hydrate on launch via SecureStore + `GET /api/auth/me`; `logout()` clears token and FCM
  registration.

* **Navigation shell:** auth stack (Login) vs app stack (bottom tabs).

### Phase 1 — MVP APK (ship early)

Target the read/act-on-the-go workflows:

* Login screen (mirror `frontend/src/pages/Login.tsx` flow).
* Dashboard / tenant list (native list replacing `TenantList.tsx`) with search.
* Tenant detail + Thread view — the core value. Rebuild `ThreadView.tsx` as a native `FlatList`
  message timeline (WhatsApp/Gmail messages) with a plain-text composer + send. Render message
  HTML with `react-native-render-html` (replacing DOM `sanitizeHtml`); rich contentEditable
  composing is deferred.
* Notifications list + unread badge (`/api/notifications*`), polling in foreground.
* Produce a signed debug/preview APK via EAS Build (`eas build -p android --profile preview`)
  that installs by sideload.

**Backend for Phase 1 [EDITED]:** none — the token-lifetime decision is **(a)**, so no
refresh-token backend work is required.

### Phase 2 — Push notifications (FCM) — backend + client

**Backend (net-new, none exists today):**

* Add a `device_tokens` table + model (device token, user_id, platform, created/last-seen) and a
  new migration (never edit deployed migrations — add a new one).
* Endpoints: `POST /api/devices/register` and `POST /api/devices/unregister` (bearer-auth, upsert
  token for current user).
* An FCM sender module (alongside the existing `notification_whatsapp_service`) that pushes to a
  user's device tokens. Store the FCM server key / service-account in env (`.env`, never committed).

* **Hook points [EDITED] — two distinct notification systems, don't conflate them:**
  * **In-app bell notifications** are created through a single choke point:
    `create_notification()` in `backend/app/services/notification_service.py:8` (called from the
    WhatsApp/email inbound ingestion paths). **Hook FCM here** — one place covers every bell
    notification. This is the primary Phase 2 push trigger.
  * **AI-draft staff pings** go through `notify_admins_of_new_draft`
    (`backend/app/services/ai_draft_notification_service.py:65`), which sends **WhatsApp messages**
    to staff phones and records `AiAutoDraftApprovalRequest` rows. It does **not** write
    `Notification` rows, so it is **not** reached by hooking `create_notification()`. Adding FCM
    for AI-draft approvals is a **separate, optional** hook in this function.

**Client:**

* `expo-notifications` (or `@react-native-firebase/messaging`): request permission, get device
  token, call `/api/devices/register` after login and on token refresh; unregister on logout.
  (Requires an EAS dev/preview build — not Expo Go.)
* Handle foreground, background, and tap-to-open (deep-link into the relevant tenant/draft screen).

### Phase 3 — Broaden coverage (optional, demand-driven)

Add native versions of Actions, AI pending drafts, and lightweight Settings as needed. Explicitly
do not port: drag/resize canvases (WorkingMemory / AI template canvases), the AI-agent
profile/template editors, OneDrive directory picker, and admin-heavy config screens — these stay
web-only. Link out to the web app for those if ever needed.

## Critical files & references

* Reuse the API contract, not the code: generate types from `GET /openapi.json`; auth request
  shapes in `backend/app/schemas/auth.py`, `backend/app/api/auth.py`.
* Auth logic to mirror: `frontend/src/store/authStore.ts`, `frontend/src/pages/Login.tsx`,
  `frontend/src/lib/sessionExpiry.ts` (401 → login), `frontend/src/lib/inactivityLogout.ts`
  (proactive refresh).
* Core UI to re-implement natively: `frontend/src/components/ThreadView.tsx`,
  `frontend/src/components/TenantList.tsx`, `frontend/src/components/NotificationBell.tsx`,
  `frontend/src/pages/Dashboard.tsx`.
* Backend touch points for push (Phase 2): `backend/app/api/notifications.py`,
  `backend/app/services/notification_service.py` (`create_notification` — the FCM hook), a new
  `backend/app/api/devices.py`, a new model + Alembic migration, and an FCM service module next to
  `notification_whatsapp_service`. AI-draft push (optional): `ai_draft_notification_service.py`.
* Config: base URL via `EXPO_PUBLIC_API_BASE_URL`; server already at
  `https://ssi-crm.theworkpc.com/api`.

## Backend changes required (summary) **[EDITED]**

* **Phase 1:** none — token-lifetime decision is **(a) accept re-logins**. (The **(b) add refresh
  tokens** path is deferred; if ever adopted it would add a model + endpoints +
  issuance/rotation/revocation.)
* **Phase 2:** additive only — new `device_tokens` model + migration, register/unregister
  endpoints, an FCM sender, and a hook in `create_notification()` (plus an optional separate hook
  in `notify_admins_of_new_draft`). No changes to existing auth, no CORS change needed for the
  native app.

## Verification

* Auth: from the RN client, log in against the live server, confirm token stored in SecureStore,
  `GET /api/auth/me` returns the user, proactive refresh swaps the token before expiry, and a
  genuine 401 routes to Login (no futile refresh attempt). Add backend regression tests only if
  new endpoints are added (Phase 2, or the optional refresh-token work).
* MVP screens: manual walkthrough on a physical Android device via the EAS `preview` APK — list
  tenants, open a thread, send a message, see it persist as a `Communication` (per WhatsApp
  invariants in CLAUDE.md, confirm outbound persists in the timeline).
* Push (Phase 2): backend `pytest` for `device_tokens` register/unregister + the FCM-send trigger
  in `create_notification()` (mock the FCM client — do NOT send real pushes in tests, per safety
  guardrails). New-migration check: `cd backend && alembic upgrade head` on a scratch DB,
  `alembic current`. End-to-end: register a device, create a `Notification`, confirm a push
  arrives and tap deep-links correctly.
* Build: `eas build -p android --profile preview` produces an installable APK; sideload and
  smoke-test on-device.

## Explicit non-goals / risks

* Not aiming for full feature parity; desktop-only canvases, rich contentEditable composing, and
  the File System Access / OneDrive feature are out of scope on mobile.
* Rich HTML email rendering and reply-composing fidelity is the hardest UI risk in the thread
  view — plain-text send first, rich later.
* **Session longevity on mobile [EDITED]:** decision **(a)** is committed — the 120-min token with
  no refresh token means a user returning after a long background gap must log in again. Accepted
  trade-off for now; the refresh-token backend work (decision **(b)**) is the deferred fallback if
  re-login frequency becomes a real annoyance.
* FCM requires a Firebase project + credentials (an external service dependency and secret to
  manage) — confirm we can create/own that Firebase project before starting Phase 2. Also note
  native FCM needs an EAS dev/preview build, not Expo Go.
