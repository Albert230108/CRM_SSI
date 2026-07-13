# CLAUDE.md — CRM_SSI Agent Instructions

## 🗺️ Project Overview & Stack

- **Project:** CRM_SSI — a short-stay tenant CRM integrating Beds24 bookings, Gmail conversations, and WhatsApp messaging/history.
- **Architecture:** Repository with three main applications:
  - `backend/` — FastAPI REST API, webhook handlers, service layer, SQLAlchemy models, Alembic migrations, and pytest tests.
  - `frontend/` — React + TypeScript frontend, built with Vite.
  - `whatsapp-service/` — Node.js/Express service using `whatsapp-web.js` for WhatsApp client sessions, send operations, and history backfill.
- **Backend framework:** FastAPI.
- **Backend language:** Python.
- **Frontend framework:** React.
- **Frontend language:** TypeScript.
- **WhatsApp service:** Node.js with Express and `whatsapp-web.js`.
- **Database:** PostgreSQL in deployed environments; SQLAlchemy ORM and Alembic migrations.
- **Key domain models:** `Tenant`, `Communication`, `TenantChannelEndpoint`, tenant phone aliases, Gmail conversations/messages, finance records.
- **WhatsApp architecture:** WhatsApp messages are persisted as `Communication` records. Manual tenant-to-chat links are stored in `TenantChannelEndpoint` rows with `channel_type="whatsapp"`. An active manual link is the authoritative relationship for inbound routing, outbound sending, history sync, and timeline filtering. [cite:4][cite:7][cite:8]

## 🛠️ Verification & Commands

Always run the relevant verification command before reporting a task as complete. Run commands from the appropriate application directory.

### Backend

- **Install dependencies:** `cd backend && pip install -r requirements.txt`
- **Run API locally:** `cd backend && uvicorn app.main:app --reload`
- **Run all tests:** `cd backend && pytest`
- **Run one test file:** `cd backend && pytest tests/test_whatsapp_thread_timeline_filtering.py`
- **Run one test:** `cd backend && pytest tests/test_whatsapp_thread_timeline_filtering.py -k "test_name"`
- **Run WhatsApp-focused tests:** `cd backend && pytest tests/test_whatsapp_*.py tests/test_tenant_channel_endpoints.py`
- **Run migrations:** `cd backend && alembic upgrade head`
- **Check current migration revision:** `cd backend && alembic current`

### Frontend

- **Install dependencies:** `cd frontend && npm install`
- **Run development server:** `cd frontend && npm run dev`
- **Production build / type validation:** `cd frontend && npm run build`
- **Lint:** `cd frontend && npm run lint`  
- **Run tests:** use the script defined in `frontend/package.json` if present.

### WhatsApp Service

- **Install dependencies:** `cd whatsapp-service && npm install`
- **Run service:** `cd whatsapp-service && npm start`
- **Run development mode:** `cd whatsapp-service && npm run dev`
- **Run all tests:** `cd whatsapp-service && npm test`
- **Run a specific test:** `cd whatsapp-service && npm test -- historyBackfill.test.js`

### Verification expectations

- For backend behavior changes, run the specific affected pytest file and relevant WhatsApp tests.
- For frontend changes, run the production build at minimum.
- For WhatsApp-service changes, run the targeted test suite plus history-backfill tests when applicable.
- Do not report a fix as complete based only on syntax checks; execute behavior-level tests.

## 🏛️ Code Conventions & Patterns

- **Exploration first:** Read the relevant models, API routes, services, tests, and frontend callers before modifying behavior.
- **Focused changes:** Preserve existing architecture and change only files necessary for the requested behavior.
- **Python:** Follow existing FastAPI, SQLAlchemy, Pydantic, and pytest patterns already used in `backend/`.
- **TypeScript:** Follow the existing React component and API-fetching patterns in `frontend/src/`.
- **JavaScript:** Follow existing Express and async/await patterns in `whatsapp-service/src/`.
- **Imports:** Keep imports explicit and grouped consistently with surrounding files. Do not introduce unnecessary wildcard imports.
- **Async/Await:** Use `async`/`await` for asynchronous code. Do not introduce raw Promise chains unless matching a required third-party API pattern.
- **Error handling:** Catch specific, expected errors. Return meaningful FastAPI `HTTPException` responses at API boundaries and do not silently swallow failures.
- **Transactions:** Commit only after related database writes are complete. Roll back on exceptions where the existing pattern requires it.
- **Logging:** Use structured, useful logs without exposing tenant-sensitive information unnecessarily. Remove temporary `print()` debugging before finalizing a change.
- **Comments:** Explain why a non-obvious business or routing decision exists, not what straightforward syntax does.
- **Tests:** Every bug fix needs a regression test reproducing the prior failure mode.

### WhatsApp-specific invariants

- A WhatsApp chat must be linked to a tenant only through an explicit manual `TenantChannelEndpoint` mapping.
- Do not auto-create bare WhatsApp endpoints during tenant creation, tenant import, or reimport.
- A valid manual link must include the WhatsApp provider/account identity and the chat namespace/identity.
- The active manual link is authoritative for inbound message routing, history backfill, outbound sends, and UI timeline filtering.
- Persist inbound, historical, and outbound WhatsApp messages as `Communication` rows with consistent tenant, account, chat, and canonical identity fields.
- Timeline filtering must never hide messages merely because an endpoint is incomplete or has no `external_chat_namespace`.
- When a manual link exists, avoid displaying messages from a different known WhatsApp chat on the same account.
- Treat WhatsApp identity variants carefully, including `@lid` and `@c.us`; compare canonical identities rather than relying only on raw string equality where provider payloads can differ.
- Outbound sends should persist a UI-visible communication immediately or reliably process the provider callback, and the frontend should refresh or update the thread afterward. [cite:7][cite:8]

## 🛑 Safety Guardrails

- **Secrets:** NEVER output, log, commit, or hard-code API keys, tokens, passwords, session data, webhook secrets, OAuth credentials, or `.env` values.
- **Environment files:** Treat `.env`, production database dumps, WhatsApp sessions, and authentication artifacts as sensitive.
- **Destructive commands:** NEVER run `rm -rf`, `git push --force`, `git reset --hard`, database resets, destructive migrations, or bulk deletions without explicit human confirmation.
- **Database safety:** Do not alter or delete production tenant, communication, endpoint, or WhatsApp-history data without explicit approval and a rollback plan.
- **Migrations:** Do not modify an already-deployed Alembic migration. Add a new migration for schema changes.
- **Scope creep:** Do not refactor unrelated code, rename unrelated files, reformat untouched files, or change unrelated API contracts unless explicitly requested.
- **External effects:** Do not send real WhatsApp messages, trigger history backfills, alter WhatsApp sessions, or call live Beds24/Gmail APIs unless explicitly instructed.
- **Endpoint ownership:** Never automatically move a WhatsApp chat link between tenants. Require an explicit manual unlink/relink action.
- **Tenant deletion:** Treat tenant deletion as destructive. Confirm expected behavior for linked endpoints and communications before changing deletion logic.

## 🔄 Workflow & Git Standards

1. Read the existing implementation and relevant tests before writing code.
2. Identify the authoritative flow and data model before changing routing, persistence, or UI filtering.
3. Implement the narrowest viable change.
4. Add or update regression tests for the requested behavior.
5. Run relevant test, build, lint, and syntax checks.
6. Review the diff for secrets, debugging logs, unrelated formatting, and unintended schema changes.
7. Report what changed, what was verified, and any remaining limitations.

### Commit messages

Use conventional commits, with the first line under 72 characters:

- `fix: keep WhatsApp history visible after reimport`
- `fix: persist outbound WhatsApp replies in timeline`
- `test: cover relinked WhatsApp history sync`
- `feat: add manual WhatsApp chat linking`
- `docs: clarify WhatsApp endpoint ownership`

### Pull request readiness

Before proposing a commit or pull request:

- Relevant tests pass.
- Frontend build passes when frontend code changed.
- WhatsApp-service tests pass when service code changed.
- Alembic migration is included when the schema changed.
- No secrets, session files, database dumps, or generated local artifacts are included.
- The diff is limited to the requested scope.
- The PR description explains expected behavior for new tenants, unlinking, relinking, reimporting, history sync, inbound messages, outbound messages, and timeline visibility where WhatsApp behavior changed.