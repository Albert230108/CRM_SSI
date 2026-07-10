# Manual WhatsApp Thread Chat Linking

## What it does

On a thread's page, the **Link chat** button opens a WhatsApp-only picker:

1. Choose a WhatsApp service/account (only WhatsApp accounts are shown — this flow does not
   handle email or other channels).
2. Browse or search the live chat list fetched straight from that account's whatsapp-service
   instance.
3. Pick the exact chat and save.

The linked chat then becomes the source of truth for that thread's WhatsApp identity: inbound
routing, CRM backfill eligibility, and the thread UI all key off the exact `chat_id` you picked
(for example `326472368@lid`).

## Full-history sync on link

Linking a chat automatically queues a background full-history resync of that chat (and it's
retriggerable any time from the thread's linked-chat panel via **Resync full history**, or by
calling `POST /api/threads/{thread_id}/whatsapp-links/{link_id}/resync`).

This matters because `whatsapp-service`'s regular history sweep caps each chat at
`WHATSAPP_HISTORY_BACKFILL_LIMIT` (default 100) messages — fine for the broad "every chat in the
account" sweep, but it silently truncated older messages for chats with more history than that.
CRM-eligible chats (including manually linked ones) now always pull their *entire* history —
`chat.fetchMessages({ limit: Infinity })` — instead of being capped, so nothing older gets
dropped. Only the indiscriminate `all=true` sweep (which touches every WhatsApp chat, not just
CRM-relevant ones) still respects the cap, to avoid pulling unbounded history for irrelevant
contacts.

## Why CHAT_ID is the primary selector

Phone-number inference is unreliable for WhatsApp `@lid` chats (linked-device identities that
have no directly derivable phone number) and for chats where the phone number on file doesn't
match the WhatsApp account's registration. An operator who can see the real chat in the picker
and match it by its exact `chat_id` gets a deterministic, unambiguous link — no guessing, no
silent mismatches. The chat list UI always shows `chat_id` as the primary, monospace, searchable
field for this reason.

## How it's wired

Manual links are stored as rows in the existing `tenant_channel_endpoints` table (channel_type
`whatsapp`, `source = 'manual'`), the same table that already powers the CRM's
account/chat-identity registry. This means manual links automatically:

- Feed `/webhooks/whatsapp/backfill-identities` (the payload whatsapp-service's
  `whatsappClient.js` uses to decide `isCrmEligibleChat`), so a manually linked `@lid` chat is
  no longer skipped with `no_crm_identity_match` during history sync.
- Participate in `resolve_tenant_for_inbound_channel`'s `exact_chat_endpoint` strategy — the
  highest-priority deterministic match after `explicit_tenant_id` and `webhook_token` — so
  inbound WhatsApp messages for a linked chat route straight to the linked thread.

No separate identity pipeline was introduced; manual linking is additive on top of the existing
registry rather than a parallel/bypass mechanism.

## API

- `GET /api/whatsapp/accounts` — WhatsApp services/accounts available for linking.
- `GET /api/whatsapp/accounts/{external_account_id}/chats?search=...` — live chat list for that
  account, proxied from the account's whatsapp-service instance (`GET /chats` there).
- `GET /api/threads/{thread_id}/whatsapp-links` — the thread's active WhatsApp link(s)
  (`?include_history=true` for unlinked history too).
- `POST /api/threads/{thread_id}/whatsapp-links` — link a chat
  (`{provider, external_account_id, chat_id, chat_display_name?, replace_existing?}`).
- `DELETE /api/threads/{thread_id}/whatsapp-links/{link_id}` — unlink (soft delete; sets
  `unlinked_at`/`unlinked_by_user_id`, stops future routing/history matching, keeps historical
  imported messages untouched).

## Limitations

- One thread can have at most one active linked chat per WhatsApp service/account. Linking a
  second chat for the same account requires `replace_existing: true`, which unlinks the previous
  one first.
- One external WhatsApp chat can belong to only one thread at a time. Attempting to link a chat
  that's already linked elsewhere returns a 409 conflict naming the other thread.
- Every link/unlink/replace/conflict is logged (`whatsapp_thread_link_created`,
  `_replaced`, `_removed`, `_conflict`, `whatsapp_chat_list_fetched`) with the acting user, so
  linking history is auditable even though rows are soft-deleted rather than hard-deleted.

## Environment configuration

- `WHATSAPP_SERVICE_ACCOUNTS` — optional JSON list of
  `{external_account_id, provider, label}` for the accounts picker. Falls back to the keys of
  `WHATSAPP_SERVICE_URL_MAP`, and finally to a single account derived from `WHATSAPP_SERVICE_URL`
  / `WHATSAPP_DEFAULT_ACCOUNT_ID` for single-account deployments.
- `WHATSAPP_SERVICE_URL_MAP` — existing multi-account routing map (JSON
  `{external_account_id: service_base_url}`), reused to resolve which whatsapp-service instance
  to query for a given account's chat list.
