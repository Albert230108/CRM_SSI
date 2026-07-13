const qrcode = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

const {
  crmWebhookRouteToken,
  crmWebhookSecret,
  crmWebhookTimeoutMs,
  crmWebhookUrl,
  crmBackfillIdentitiesUrl,
  crmOutboundResolutionUrl,
  reconnectDelayMs,
  whatsappClientId,
  whatsappHistoryBackfillLimit,
  whatsappHistoryBackfillEnabled,
} = require("./config");
const { resolveOutboundTenantOwnership } = require("./outboundResolution");
const { buildWhatsAppIdentityCandidates, getCanonicalWhatsAppIdentity, normalizeWhatsAppChatId, normalizeWhatsAppPhone } = require("./whatsappIdentity");

let client = null;
let ready = false;
let initializingPromise = null;
let reconnectTimer = null;
let shuttingDown = false;
let startupBackfillTriggered = false;
let forwardedMessageIds = new Set();
const pendingOutboundTenantByMessageId = new Map();
const pendingOutboundTenantByChatId = new Map();
const pendingOutboundTenantByIdentityKey = new Map();
let outboundCaptureCount = 0;

function getChatId(chat) {
  return chat?.id?._serialized || chat?.id?.serialized || chat?.id || null;
}

function getChatName(chat) {
  const explicitName = chat?.name || chat?.formattedTitle || chat?.contact?.pushname || chat?.contact?.name || null;
  if (explicitName) {
    return explicitName;
  }
  // Raw chat ids (e.g. "37284873@lid") are opaque WhatsApp-internal identifiers, not
  // phone numbers — only fall back to a displayable value when it's an actual number.
  const phone = normalizeWhatsAppPhone(getChatId(chat));
  return phone ? `+${phone}` : null;
}

function getMemoryTenantId({ messageId, chatId, identityKey }) {
  const normalizedChatId = normalizeWhatsAppChatId(chatId);
  const normalizedIdentityKey = normalizeWhatsAppChatId(identityKey);
  if (messageId && pendingOutboundTenantByMessageId.has(messageId)) {
    return pendingOutboundTenantByMessageId.get(messageId) ?? null;
  }
  if (normalizedIdentityKey && pendingOutboundTenantByIdentityKey.has(normalizedIdentityKey)) {
    return pendingOutboundTenantByIdentityKey.get(normalizedIdentityKey) ?? null;
  }
  if (normalizedChatId && pendingOutboundTenantByChatId.has(normalizedChatId)) {
    return pendingOutboundTenantByChatId.get(normalizedChatId) ?? null;
  }
  return null;
}

async function lookupDurableOutboundTenant({ messageId, chatId, identityKey, externalAccountId }) {
  if (!crmOutboundResolutionUrl) {
    return { found: false, resolution_strategy: "unconfigured" };
  }

  const query = new URLSearchParams();
  if (messageId) {
    query.set("provider_message_id", messageId);
  }
  if (chatId) {
    query.set("whatsapp_chat_id", chatId);
  }
  if (identityKey) {
    query.set("whatsapp_identity_key", identityKey);
  }
  if (externalAccountId) {
    query.set("external_account_id", externalAccountId);
  }

  const headers = {};
  if (crmWebhookSecret) {
    headers["X-Webhook-Secret"] = crmWebhookSecret;
  }
  if (crmWebhookRouteToken) {
    headers["X-Webhook-Token"] = crmWebhookRouteToken;
  }

  const url = `${crmOutboundResolutionUrl}?${query.toString()}`;
  try {
    const response = await fetch(url, {
      method: "GET",
      headers,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      return payload || { found: false, resolution_strategy: `http_${response.status}` };
    }
    return payload || { found: false, resolution_strategy: "empty_response" };
  } catch (error) {
    return {
      found: false,
      resolution_strategy: "lookup_error",
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function normalizeWhatsAppId(input) {
  const value = String(input || "").trim();
  if (!value) {
    return null;
  }

  const atIndex = value.indexOf("@");
  const candidate = atIndex >= 0 ? value.slice(0, atIndex) : value;
  const digits = candidate.replace(/\D+/g, "");
  return digits || candidate || null;
}

function normalizeChatIdentity(input) {
  const value = String(input || "").trim().toLowerCase();
  return value || null;
}

function normalizePhoneIdentity(input) {
  const value = String(input || "").trim();
  if (!value) {
    return null;
  }
  const lowered = value.toLowerCase();
  if (lowered.endsWith("@c.us")) {
    const digits = lowered.split("@", 1)[0].replace(/\D+/g, "");
    if (digits.length < 7 || /^0+$/.test(digits)) {
      return null;
    }
    return digits;
  }
  if (lowered.includes("@")) {
    return null;
  }
  const digits = value.replace(/\D+/g, "");
  if (digits.length < 7 || /^0+$/.test(digits)) {
    return null;
  }
  return digits || null;
}

function addUniqueValue(target, seen, value) {
  const normalized = value == null ? null : String(value).trim().toLowerCase();
  if (normalized && !seen.has(normalized)) {
    seen.add(normalized);
    target.push(normalized);
  }
}

function buildPhoneCandidateKeys(input) {
  const raw = String(input || "").trim();
  if (!raw) {
    return [];
  }

  const candidates = [];
  const seen = new Set();
  const add = (value) => {
    const normalized = normalizePhoneIdentity(value);
    if (normalized && !seen.has(normalized)) {
      seen.add(normalized);
      candidates.push(normalized);
    }
  };

  add(raw);
  add(raw.replace(/^wa_id[:=]\s*/i, ""));

  if (raw.toLowerCase().endsWith("@c.us")) {
    add(raw.split("@", 1)[0]);
  }
  if (raw.startsWith("+")) {
    add(raw.slice(1));
  }
  if (raw.startsWith("00")) {
    add(raw.slice(2));
  }
  if (/[\s\-()./]/.test(raw)) {
    add(raw.replace(/\D+/g, ""));
  }

  return candidates;
}

function buildChatCandidateKeys(input) {
  const raw = String(input || "").trim().toLowerCase();
  if (!raw) {
    return [];
  }

  const candidates = [];
  const seen = new Set();
  const add = (value) => {
    const normalized = normalizeChatIdentity(value);
    if (normalized && !seen.has(normalized)) {
      seen.add(normalized);
      candidates.push(normalized);
    }
  };

  add(raw);
  const atIndex = raw.indexOf("@");
  const base = atIndex >= 0 ? raw.slice(0, atIndex) : raw;
  const suffix = atIndex >= 0 ? raw.slice(atIndex + 1) : "";
  if (suffix === "g.us") {
    return candidates;
  }
  if (suffix === "c.us") {
    const phone = normalizePhoneIdentity(raw);
    if (phone) {
      add(phone);
      add(`${phone}@c.us`);
    }
    return candidates;
  }
  const phone = normalizePhoneIdentity(base);
  if (phone) {
    add(phone);
    if (suffix) {
      add(`${phone}@c.us`);
    }
  }
  if (base && !raw.includes("@")) {
    add(base);
  }
  return candidates;
}

function buildEligibleIdentityIndex(payload) {
  const chatIds = new Set();
  const phoneNumbers = new Set();
  const entries = Array.isArray(payload?.entries) ? payload.entries : [];
  const trustedIdentities = Array.isArray(payload?.trusted_identities) ? payload.trusted_identities : [];

  const addChatValues = (values) => {
    for (const value of values) {
      for (const candidate of buildChatCandidateKeys(value)) {
        chatIds.add(candidate);
      }
    }
  };

  const addPhoneValues = (values) => {
    for (const value of values) {
      for (const candidate of buildPhoneCandidateKeys(value)) {
        phoneNumbers.add(candidate);
      }
    }
  };

  for (const entry of entries) {
    addChatValues([
      ...(Array.isArray(entry?.chat_ids) ? entry.chat_ids : []),
      ...(Array.isArray(entry?.external_chat_namespaces) ? entry.external_chat_namespaces : []),
    ]);
    addPhoneValues([
      ...(Array.isArray(entry?.phone_numbers) ? entry.phone_numbers : []),
      ...(Array.isArray(entry?.external_phone_ids) ? entry.external_phone_ids : []),
    ]);
  }

  for (const identity of trustedIdentities) {
    addChatValues([
      identity?.whatsapp_chat_id,
      identity?.whatsapp_identity_key,
      identity?.external_chat_namespace,
    ]);
    addPhoneValues([
      identity?.whatsapp_normalized_phone,
      identity?.external_phone_id,
      identity?.phone_number,
    ]);
  }

  return {
    chatIds,
    phoneNumbers,
    totalTenants: Number(payload?.total_tenants || entries.length || 0),
    totalActiveEndpoints: Number(payload?.total_active_endpoints || 0),
    totalIdentityRecords: Number(payload?.total_identity_records || 0),
    entries,
    trustedIdentities,
  };
}

async function fetchCrmEligibleChatIdentities() {
  if (!crmBackfillIdentitiesUrl) {
    throw new Error("CRM backfill identities URL is not configured");
  }

  const headers = {};
  if (crmWebhookSecret) {
    headers["X-Webhook-Secret"] = crmWebhookSecret;
  }
  if (crmWebhookRouteToken) {
    headers["X-Webhook-Token"] = crmWebhookRouteToken;
  }

  const response = await fetch(crmBackfillIdentitiesUrl, {
    method: "GET",
    headers,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload && typeof payload === "object"
      ? String(payload.error || payload.detail || `HTTP ${response.status}`)
      : `HTTP ${response.status}`;
    throw new Error(`CRM backfill identities lookup failed: ${message}`);
  }
  if (!payload || typeof payload !== "object") {
    throw new Error("CRM backfill identities lookup returned invalid JSON");
  }
  return buildEligibleIdentityIndex(payload);
}

function getChatIdentityCandidates(chat) {
  return buildChatCandidateKeys(getChatId(chat));
}

function isCrmEligibleChat(chat, eligibleIdentityIndex) {
  if (!chat || !eligibleIdentityIndex) {
    return false;
  }
  const candidates = getChatIdentityCandidates(chat);
  return candidates.some((candidate) => eligibleIdentityIndex.chatIds.has(candidate) || eligibleIdentityIndex.phoneNumbers.has(candidate));
}

function describeChatSkipReason(chat, eligibleIdentityIndex) {
  const chatId = getChatId(chat);
  if (!chatId) {
    return "missing_chat_id";
  }
  const candidates = getChatIdentityCandidates(chat);
  if (!eligibleIdentityIndex || (!eligibleIdentityIndex.chatIds.size && !eligibleIdentityIndex.phoneNumbers.size)) {
    return "crm_identity_lookup_empty";
  }
  if (candidates.some((candidate) => eligibleIdentityIndex.chatIds.has(candidate))) {
    return null;
  }
  if (candidates.some((candidate) => eligibleIdentityIndex.phoneNumbers.has(candidate))) {
    return null;
  }
  return "no_crm_identity_match";
}

// Message types that carry real conversational content but have no `body`/`caption` text of
// their own (media, location, contacts, etc.) — these get a readable placeholder instead of
// being silently dropped. Types NOT listed here (call logs, e2e/group notifications, revoked
// "message deleted" placeholders, unknown system events) genuinely have nothing to show and are
// skipped on purpose.
const MEDIA_TYPE_LABELS = {
  image: "[Image]",
  video: "[Video]",
  audio: "[Audio]",
  ptt: "[Voice message]",
  sticker: "[Sticker]",
  document: "[Document]",
  location: "[Location]",
  vcard: "[Contact card]",
  multi_vcard: "[Contact cards]",
  order: "[Order]",
  product: "[Product]",
  poll_creation: "[Poll]",
  list: "[List message]",
  buttons_response: "[Button reply]",
  template_button_reply: "[Button reply]",
};

function describeMediaPlaceholder(message) {
  const type = message?.type;
  const label = MEDIA_TYPE_LABELS[type];
  if (!label) {
    return null;
  }
  const filename = message?.filename || message?._data?.filename;
  return filename ? `${label} ${filename}` : label;
}

function extractText(message) {
  for (const key of ["body", "caption", "text", "content"]) {
    const value = message?.[key];
    if (value) {
      return String(value);
    }
  }
  return describeMediaPlaceholder(message) || "";
}

function normalizeHistoryValue(value) {
  return String(value || "").trim();
}

function sortBackfillMessages(left, right) {
  const leftTimestamp = Number(left?.timestamp || 0);
  const rightTimestamp = Number(right?.timestamp || 0);
  if (leftTimestamp !== rightTimestamp) {
    return leftTimestamp - rightTimestamp;
  }
  return String(left?.id?._serialized || "").localeCompare(String(right?.id?._serialized || ""));
}

function buildHistoryDedupeKey(message, chatId, direction) {
  const text = extractText(message);
  const timestamp = Number(message?.timestamp || 0);
  const sender = normalizeHistoryValue(message?.author || message?.from || null);
  const recipient = normalizeHistoryValue(message?.to || chatId || null);
  return [
    normalizeHistoryValue(chatId),
    normalizeHistoryValue(direction),
    timestamp,
    text,
    sender,
    recipient,
  ].join("|");
}

function buildCrmPayload(message, direction, overrides = {}) {
  const text = extractText(message);
  const timestamp = message?.timestamp;
  const author = message?.author || null;
  const sender = overrides.sender || author || message?.from || null;
  const recipient = overrides.to || message?.to || message?.from || null;
  const identity = getCanonicalWhatsAppIdentity({
    direction,
    whatsapp_raw_chat_id: overrides.whatsapp_chat_id || message?.chatId || message?.from || message?.to || null,
    whatsapp_chat_id: overrides.whatsapp_chat_id || message?.chatId || message?.from || message?.to || null,
    whatsapp_identity_key: overrides.whatsapp_identity_key || null,
    whatsapp_normalized_phone: overrides.whatsapp_normalized_phone || null,
    sender,
    recipient,
    sender_normalized: overrides.sender_normalized || normalizeWhatsAppPhone(sender),
    recipient_normalized: overrides.recipient_normalized || normalizeWhatsAppPhone(recipient),
    is_group: overrides.is_group ?? null,
  }, { direction });
  const chatId = identity.rawChatId || overrides.whatsapp_chat_id || message?.chatId || message?.from || message?.to || null;

  return {
    direction,
    from: sender,
    sender,
    sender_raw: sender,
    sender_normalized: normalizeWhatsAppPhone(sender),
    to: recipient,
    recipient,
    recipient_normalized: normalizeWhatsAppPhone(recipient),
    message: text,
    body: text,
    text,
    timestamp: Number.isFinite(Number(timestamp)) ? Number(timestamp) : Math.floor(Date.now() / 1000),
    whatsapp_message_id: message?.id?._serialized || overrides.whatsapp_message_id || null,
    whatsapp_chat_id: chatId,
    whatsapp_raw_chat_id: chatId,
    whatsapp_identity_key: identity.canonicalChatId,
    whatsapp_normalized_phone: identity.normalizedPhone,
    whatsapp_author: author,
    whatsapp_type: message?.type || null,
    whatsapp_client_id: whatsappClientId || null,
    tenant_id: overrides.tenant_id ?? null,
    provider: "whatsapp-service",
    external_account_id: whatsappClientId || null,
    whatsapp_endpoint_id: overrides.whatsapp_endpoint_id ?? null,
    is_group: identity.isGroup,
    source: overrides.source ?? null,
  };
}

async function forwardCrmMessage(payload, contextLabel, options = {}) {
  if (!crmWebhookUrl) {
    console.warn(`CRM WhatsApp webhook URL is not configured; ${contextLabel} messages will not be forwarded.`);
    return false;
  }

  // The in-memory forwardedMessageIds cache only tracks "did this process already send this
  // message id", not "does the CRM still have it" - it can't see a relink or a CRM-side data
  // reset that happened without restarting this service. History/backfill forwarding relies on
  // the CRM's own provider_message_id dedup instead (see _find_existing_inbound_whatsapp_communication),
  // so it opts out of this cache to make "resync full history" actually able to redeliver.
  if (!options.skipForwardedCache && payload.whatsapp_message_id && forwardedMessageIds.has(payload.whatsapp_message_id)) {
    console.info(
      "Skipping duplicate %s WhatsApp message for CRM forwarding: message_id=%s",
      contextLabel,
      payload.whatsapp_message_id,
    );
    return false;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), crmWebhookTimeoutMs);

  try {
    console.info(
      "Forwarding %s WhatsApp message to CRM: message_id=%s chat_id=%s client_id=%s",
      contextLabel,
      payload.whatsapp_message_id,
      payload.whatsapp_chat_id,
      payload.whatsapp_client_id,
    );

    const response = await fetch(crmWebhookUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(crmWebhookRouteToken ? { "X-Webhook-Token": crmWebhookRouteToken } : {}),
        ...(crmWebhookSecret ? { "X-Webhook-Secret": crmWebhookSecret } : {}),
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      const responseText = await response.text().catch(() => "");
      throw new Error(`CRM webhook responded with ${response.status}${responseText ? `: ${responseText}` : ""}`);
    }

    if (payload.whatsapp_message_id) {
      forwardedMessageIds.add(payload.whatsapp_message_id);
    }
    return true;
  } finally {
    clearTimeout(timeout);
  }
}

async function forwardInboundMessage(message) {
  if (!message || message?.isStatus) {
    return false;
  }
  if (message?.fromMe) {
    return forwardOutboundCapturedMessage(message, message?.chatId || message?.to || message?.from || null, message?.to || null, "inbound-hook");
  }

  const text = extractText(message);
  if (!text) {
    return false;
  }

  const payload = buildCrmPayload(message, "inbound", {
    sender: message?.author || message?.from || null,
    whatsapp_chat_id: message?.from || null,
    source: "history",
  });
  return forwardCrmMessage(payload, "inbound");
}

async function forwardOutboundMessage(message, chatId, recipient, tenantId = null) {
  const text = extractText(message);
  if (!text) {
    return false;
  }

  const payload = buildCrmPayload(message, "outbound", {
    to: recipient || chatId || message?.to || null,
    whatsapp_chat_id: chatId || message?.from || message?.to || null,
    whatsapp_message_id: message?.id?._serialized || null,
    tenant_id: tenantId,
  });
  return forwardCrmMessage(payload, "outbound");
}

async function forwardOutboundCapturedMessage(message, chatId, recipient, contextLabel = "outbound", tenantId = null) {
  if (!message?.fromMe) {
    return false;
  }

  console.info(
    "Resolved outbound WhatsApp tenant for %s: message_id=%s tenant_id=%s",
    contextLabel,
    message?.id?._serialized || null,
    tenantId || null,
  );

  const identity = getCanonicalWhatsAppIdentity({
    direction: "outbound",
    whatsapp_chat_id: chatId || message?.chatId || message?.from || message?.to || null,
    sender: message?.author || message?.from || null,
    recipient: recipient || message?.to || chatId || null,
    to: recipient || message?.to || chatId || null,
    from: message?.from || null,
  }, { direction: "outbound" });

  const sent = await forwardOutboundMessage(message, chatId, recipient, tenantId);
  if (chatId) {
    pendingOutboundTenantByChatId.delete(normalizeWhatsAppChatId(chatId));
  }
  if (identity.canonicalChatId) {
    pendingOutboundTenantByIdentityKey.delete(identity.canonicalChatId);
  }
  if (sent) {
    outboundCaptureCount += 1;
    console.info(JSON.stringify({
      event: "whatsapp_outbound_captured",
      context: contextLabel,
      captured_count: outboundCaptureCount,
      whatsapp_message_id: message?.id?._serialized || null,
      whatsapp_chat_id: chatId || message?.chatId || message?.from || message?.to || null,
    }));
  }
  return sent;
}

function normalizeRecipient(input) {
  const value = String(input || "").trim();
  if (!value) {
    return null;
  }
  if (value.includes("@")) {
    return value;
  }
  const digits = value.replace(/\D+/g, "");
  if (!digits) {
    return null;
  }
  return `${digits}@c.us`;
}

function isRelevantChat(chat) {
  if (!chat) {
    return false;
  }
  if (chat?.isGroup || String(chat?.id?._serialized || chat?.id || "").endsWith("@g.us")) {
    return false;
  }
  return true;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// whatsapp-web.js's Chat.fetchMessages runs `searchOptions` through a Puppeteer page.evaluate
// call, which serializes arguments across the browser boundary. Infinity does not survive that
// serialization (it arrives as null/0 on the page side), and its internal pagination loop is
// `while (searchOptions.limit > 0) { loadEarlierMsgs... }` — a falsy limit means that loop never
// runs at all, so it silently returns only whatever's already cached in memory (as few as a
// single message). Use a large *finite* number instead: the loop still terminates naturally
// once loadEarlierMsgs stops returning new messages (i.e. the chat's real history is exhausted).
const FULL_HISTORY_FETCH_LIMIT = 1_000_000;

async function backfillChatHistory(chat, options = {}) {
  // fullHistory pulls the entire chat history from the store (no page cap) instead of the
  // last `limit` messages. Used for CRM-eligible chats (including manually linked ones), since
  // capping at whatsappHistoryBackfillLimit (default 100) silently truncated older messages.
  const fullHistory = Boolean(options.fullHistory);
  const limit = fullHistory
    ? FULL_HISTORY_FETCH_LIMIT
    : Math.max(1, Number.parseInt(String(options.limit || whatsappHistoryBackfillLimit || 100), 10) || whatsappHistoryBackfillLimit || 100);
  if (!chat) {
    return { imported: 0, deduped: 0, failed: 0, inbound: 0, outbound: 0, fetched: 0 };
  }

  if (!isRelevantChat(chat)) {
    return { imported: 0, deduped: 0, failed: 0, inbound: 0, outbound: 0, fetched: 0, skippedChat: true };
  }

  const chatId = getChatId(chat);
  const chatName = getChatName(chat);
  const logBase = {
    chat_id: chatId,
    chat_name: chatName,
    isGroup: Boolean(chat?.isGroup || String(chatId || "").endsWith("@g.us")),
  };

  if (typeof chat.syncHistory === "function") {
    try {
      await chat.syncHistory();
      console.info(JSON.stringify({ event: "whatsapp_history_sync_success", ...logBase }));
      const postSyncDelayMs = Number.parseInt(String(options.postSyncDelayMs ?? 1500), 10) || 0;
      if (postSyncDelayMs > 0) {
        await sleep(postSyncDelayMs);
      }
    } catch (error) {
      console.error(JSON.stringify({
        event: "whatsapp_history_sync_failure",
        ...logBase,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }

  let messages = [];
  try {
    messages = typeof chat.fetchMessages === "function" ? await chat.fetchMessages({ limit }) : [];
  } catch (error) {
    console.error(JSON.stringify({
      event: "whatsapp_history_fetch_failure",
      ...logBase,
      error: error instanceof Error ? error.message : String(error),
    }));
    throw error;
  }

  const ordered = Array.isArray(messages)
    ? messages.slice().sort(sortBackfillMessages)
    : [];

  let imported = 0;
  let deduped = 0;
  let skippedNoContent = 0;
  let failed = 0;
  let inbound = 0;
  let outbound = 0;
  const fetched = ordered.length;
  const seenIds = new Set();

  for (const message of ordered) {
    const whatsappMessageId = message?.id?._serialized || null;
    const direction = message?.fromMe ? "outbound" : "inbound";
    const dedupeKey = whatsappMessageId || buildHistoryDedupeKey(message, chatId, direction);
    if (seenIds.has(dedupeKey)) {
      deduped += 1;
      continue;
    }
    seenIds.add(dedupeKey);

    const text = extractText(message);
    if (!text) {
      // Genuinely contentless events (call logs, group/e2e notifications, "message deleted"
      // placeholders, unrecognized system events) — nothing to show, not a duplicate.
      skippedNoContent += 1;
      console.info(JSON.stringify({
        event: "whatsapp_history_message_skipped_no_content",
        ...logBase,
        whatsapp_message_id: whatsappMessageId,
        whatsapp_type: message?.type || null,
      }));
      continue;
    }
    if (direction === "outbound") {
      outbound += 1;
    } else {
      inbound += 1;
    }

    const payload = buildCrmPayload(message, direction, {
      to: direction === "outbound" ? normalizeRecipient(chat?.id?.user || chat?.id || message?.to || message?.from) : null,
      sender: message?.author || message?.from || null,
      whatsapp_chat_id: chat?.id?._serialized || chat?.id || message?.from || message?.to || null,
      whatsapp_message_id: whatsappMessageId,
      source: "history",
    });

    try {
      const forwarded = await forwardCrmMessage(payload, `history-${direction}`, { skipForwardedCache: true });
      if (forwarded) {
        imported += 1;
      } else {
        // forwardCrmMessage returned false without making a request (webhook URL not
        // configured) - it must not be counted as a fresh delivery to the CRM.
        deduped += 1;
      }
    } catch (error) {
      failed += 1;
      console.error(JSON.stringify({
        event: "whatsapp_history_import_failure",
        ...logBase,
        whatsapp_message_id: whatsappMessageId,
        direction,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }

  console.info(JSON.stringify({
    event: "whatsapp_history_chat_summary",
    ...logBase,
    fetched_count: fetched,
    inbound_count: inbound,
    outbound_count: outbound,
    imported_count: imported,
    deduped_count: deduped,
    skipped_no_content_count: skippedNoContent,
    failed_count: failed,
  }));

  return { imported, deduped, skippedNoContent, failed, inbound, outbound, fetched };
}

async function backfillAllChats({
  limit = whatsappHistoryBackfillLimit,
  postSyncDelayMs = 0,
  clientOverride = null,
  readyOverride = null,
  all = false,
  chatId = null,
  eligibleIdentityIndex = null,
  fetchEligibleIdentityIndex = fetchCrmEligibleChatIdentities,
} = {}) {
  const activeClient = clientOverride || client;
  const isClientReady = readyOverride ?? ready;
  if (!activeClient || !isClientReady) {
    throw new Error("WhatsApp client is not ready");
  }

  const chats = typeof activeClient.getChats === "function" ? await activeClient.getChats() : [];
  let orderedChats = Array.isArray(chats)
    ? chats.slice().sort((a, b) => String(getChatId(a) || "").localeCompare(String(getChatId(b) || "")))
    : [];

  const targetChatId = chatId ? String(chatId).trim() : null;
  if (targetChatId) {
    orderedChats = orderedChats.filter((chat) => String(getChatId(chat) || "") === targetChatId);
  }

  let resolvedEligibleIdentityIndex = eligibleIdentityIndex;
  let crmLookupFailed = null;
  if (!resolvedEligibleIdentityIndex) {
    try {
      resolvedEligibleIdentityIndex = await fetchEligibleIdentityIndex();
    } catch (error) {
      crmLookupFailed = error instanceof Error ? error.message : String(error);
      if (!all) {
        throw error;
      }
      console.warn(JSON.stringify({
        event: "whatsapp_history_crm_identity_lookup_failed",
        error: crmLookupFailed,
        fallback_scope: "all",
      }));
    }
  }

  const crmEligibleChats = orderedChats.filter((chat) => isCrmEligibleChat(chat, resolvedEligibleIdentityIndex));
  const chatsToSync = targetChatId ? orderedChats : (all ? orderedChats : crmEligibleChats);
  const skippedChats = orderedChats.length - chatsToSync.length;

  if (!targetChatId) {
    for (const chat of orderedChats) {
      if (all || isCrmEligibleChat(chat, resolvedEligibleIdentityIndex)) {
        continue;
      }
      console.info(JSON.stringify({
        event: "whatsapp_history_chat_skipped",
        chat_id: getChatId(chat),
        chat_name: getChatName(chat),
        reason: describeChatSkipReason(chat, resolvedEligibleIdentityIndex),
        scope: "crm_scoped",
      }));
    }
  }

  let imported = 0;
  let deduped = 0;
  let skippedNoContent = 0;
  let failed = 0;
  let inbound = 0;
  let outbound = 0;
  let fetched = 0;

  // CRM-eligible chats (including manually linked ones) are a small, deliberately-selected set,
  // so it's safe and correct to pull their *entire* history rather than the last `limit`
  // messages. Only the broad "all"-scope sweep (every chat in the account) keeps the cap, to
  // avoid pulling massive irrelevant history for every random contact.
  const fullHistory = Boolean(targetChatId) || !all;

  for (const chat of chatsToSync) {
    try {
      const result = await backfillChatHistory(chat, { limit, postSyncDelayMs, fullHistory });
      imported += result.imported;
      deduped += result.deduped;
      skippedNoContent += result.skippedNoContent || 0;
      failed += result.failed;
      inbound += result.inbound;
      outbound += result.outbound;
      fetched += result.fetched;
    } catch (error) {
      failed += 1;
      console.error(JSON.stringify({
        event: "whatsapp_history_sync_failure",
        chat_id: getChatId(chat),
        chat_name: getChatName(chat),
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }

  console.info(JSON.stringify({
    event: "whatsapp_history_backfill_summary",
    chats_in_whatsapp_count: orderedChats.length,
    crm_eligible_chats_count: crmEligibleChats.length,
    chats_synced_count: chatsToSync.length,
    skipped_chats_count: skippedChats,
    imported_count: imported,
    deduped_count: deduped,
    skipped_no_content_count: skippedNoContent,
    failed_count: failed,
    scope: all ? "all" : "crm_scoped",
    crm_identity_lookup_failed: Boolean(crmLookupFailed),
  }));

  return {
    scope: all ? "all" : "crm_scoped",
    total_chats_in_whatsapp: orderedChats.length,
    total_crm_eligible_chats: crmEligibleChats.length,
    total_synced_chats: chatsToSync.length,
    skipped_chats: skippedChats,
    chats: chatsToSync.length,
    scanned: orderedChats.length,
    fetched,
    inbound,
    outbound,
    imported,
    deduped,
    skippedNoContent,
    failed,
    crm_identity_lookup_failed: Boolean(crmLookupFailed),
  };
}

async function maybeRunStartupBackfill() {
  if (!whatsappHistoryBackfillEnabled || startupBackfillTriggered) {
    return;
  }

  startupBackfillTriggered = true;
  try {
    const result = await backfillAllChats({ limit: whatsappHistoryBackfillLimit, all: false, postSyncDelayMs: 0 });
    console.info(
      "Startup WhatsApp history backfill finished: chats=%s imported=%s deduped=%s failed=%s",
      result.chats,
      result.imported,
      result.deduped,
      result.failed,
    );
  } catch (error) {
    console.error("Startup WhatsApp history backfill failed:", error);
  }
}

function attachClientEvents(nextClient) {
  nextClient.on("qr", (qr) => {
    console.log("Scan this QR code with WhatsApp to connect the service:");
    qrcode.generate(qr, { small: true });
  });

  nextClient.on("authenticated", () => {
    console.log("WhatsApp session authenticated.");
  });

  nextClient.on("ready", () => {
    ready = true;
    console.log("WhatsApp client ready.");
    void maybeRunStartupBackfill();
  });

  nextClient.on("message", (message) => {
    void forwardInboundMessage(message).catch((error) => {
      console.error("Failed to forward inbound WhatsApp message to CRM:", error);
    });
  });

  nextClient.on("message_create", (message) => {
    if (!message?.fromMe) {
      return;
    }
    const messageId = message?.id?._serialized || null;
    const chatId = message?.chatId || message?.to || message?.from || null;
    const identity = getCanonicalWhatsAppIdentity({
      direction: "outbound",
      whatsapp_chat_id: chatId,
      sender: message?.author || message?.from || null,
      recipient: message?.to || null,
      to: message?.to || null,
      from: message?.from || null,
    }, { direction: "outbound" });
    const externalAccountId = whatsappClientId || null;
    const logBase = {
      event: "whatsapp_outbound_resolution",
      message_id: messageId,
      chat_id: chatId,
      whatsapp_identity_key: identity.canonicalChatId,
      whatsapp_normalized_phone: identity.normalizedPhone,
      external_account_id: externalAccountId,
      tenant_id_received: null,
    };
    const attemptForward = async (remainingAttempts = 10) => {
      if (messageId && forwardedMessageIds.has(messageId)) {
        return;
      }
      const resolved = await resolveOutboundTenantOwnership({
        messageId,
        chatId,
        identityKey: identity.canonicalChatId,
        normalizedPhone: identity.normalizedPhone,
        externalAccountId,
        lookupDurableTenant: lookupDurableOutboundTenant,
        getMemoryTenantId,
      });
      if (!resolved && remainingAttempts > 0) {
        await sleep(100);
        return attemptForward(remainingAttempts - 1);
      }
      if (!resolved) {
        console.warn(JSON.stringify({
          ...logBase,
          resolution_source: "unresolved",
          resolution_strategy: "unresolved",
          reason: "tenant_id could not be resolved",
        }));
        return;
      }
      console.info(JSON.stringify({
        ...logBase,
        tenant_id_received: resolved.tenantId,
        resolution_source: resolved.resolutionSource,
        resolution_strategy: resolved.resolutionStrategy,
        matched_value: resolved.matchedValue,
      }));
      void forwardOutboundCapturedMessage(
        message,
        chatId,
        message?.to || null,
        "message_create",
        resolved.tenantId,
      ).catch((error) => {
        console.error("Failed to forward outbound WhatsApp message to CRM:", error);
      });
    };
    void attemptForward();
  });

  nextClient.on("auth_failure", (message) => {
    ready = false;
    console.error(`WhatsApp authentication failed: ${message}`);
    scheduleReconnect();
  });

  nextClient.on("disconnected", (reason) => {
    ready = false;
    console.warn(`WhatsApp client disconnected: ${reason}`);
    scheduleReconnect();
  });
}

function createClient() {
  const nextClient = new Client({
    authStrategy: new LocalAuth({
      clientId: `${whatsappClientId}-crm`,
      dataPath: "/var/lib/whatsapp-service-crm/auth",
    }),
    puppeteer: {
      headless: true,
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
  });

  attachClientEvents(nextClient);
  return nextClient;
}

function scheduleReconnect() {
  if (shuttingDown || reconnectTimer) {
    return;
  }

  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    try {
      await initializeClient(true);
    } catch (error) {
      console.error("WhatsApp reconnect attempt failed:", error);
      scheduleReconnect();
    }
  }, reconnectDelayMs);
}

async function initializeClient(forceRestart = false) {
  if (initializingPromise) {
    return initializingPromise;
  }

  if (client && forceRestart) {
    try {
      await client.destroy();
    } catch (error) {
      console.warn("Failed to destroy previous WhatsApp client before restart:", error);
    }
    client = null;
  }

  if (!client) {
    client = createClient();
  }

  initializingPromise = client
    .initialize()
    .catch((error) => {
      console.error("Failed to initialize WhatsApp client:", error);
      scheduleReconnect();
      throw error;
    })
    .finally(() => {
      initializingPromise = null;
    });

  return initializingPromise;
}

function isReady() {
  return ready;
}

function getChatLastMessageTimestamp(chat) {
  const timestamp = chat?.lastMessage?.timestamp ?? chat?.timestamp ?? null;
  if (!Number.isFinite(Number(timestamp))) {
    return null;
  }
  return new Date(Number(timestamp) * 1000).toISOString();
}

function getChatLastMessagePreview(chat) {
  const body = chat?.lastMessage?.body;
  if (typeof body !== "string" || !body.trim()) {
    return null;
  }
  const trimmed = body.trim();
  return trimmed.length > 160 ? `${trimmed.slice(0, 160)}...` : trimmed;
}

async function listChats({ externalAccountId, search = "", limit = 200, offset = 0, clientOverride = null, readyOverride = null } = {}) {
  const activeClient = clientOverride || client;
  const isClientReady = readyOverride ?? ready;
  if (!activeClient || !isClientReady) {
    throw new Error("WhatsApp client is not ready");
  }
  if (externalAccountId && externalAccountId !== whatsappClientId) {
    throw new Error(`WhatsApp account id mismatch: requested ${externalAccountId} but this service is configured for ${whatsappClientId}`);
  }

  const chats = typeof activeClient.getChats === "function" ? await activeClient.getChats() : [];
  const normalized = (Array.isArray(chats) ? chats : []).map((chat) => ({
    chat_id: String(getChatId(chat) || ""),
    chat_name: getChatName(chat) || null,
    provider: "whatsapp-service",
    external_account_id: whatsappClientId || null,
    last_message_timestamp: getChatLastMessageTimestamp(chat),
    last_message_preview: getChatLastMessagePreview(chat),
    is_group: Boolean(chat?.isGroup),
  }));

  const normalizedSearch = String(search || "").trim().toLowerCase();
  const searchDigits = normalizedSearch.replace(/\D+/g, "");
  const filtered = normalizedSearch
    ? normalized.filter((chat) => {
        const chatIdLower = chat.chat_id.toLowerCase();
        const chatNameLower = String(chat.chat_name || "").toLowerCase();
        const previewLower = String(chat.last_message_preview || "").toLowerCase();
        if (
          chatIdLower.includes(normalizedSearch) ||
          chatNameLower.includes(normalizedSearch) ||
          previewLower.includes(normalizedSearch)
        ) {
          return true;
        }
        // Compare digits-only so phone numbers match regardless of spaces/dashes/parens
        // in either the query or the stored chat id/name (e.g. "351 912 345 678" vs "351912345678").
        if (searchDigits.length >= 3) {
          const chatIdDigits = chatIdLower.replace(/\D+/g, "");
          const chatNameDigits = chatNameLower.replace(/\D+/g, "");
          if (chatIdDigits.includes(searchDigits) || chatNameDigits.includes(searchDigits)) {
            return true;
          }
        }
        return false;
      })
    : normalized;

  filtered.sort((a, b) => {
    const aTime = a.last_message_timestamp ? new Date(a.last_message_timestamp).getTime() : 0;
    const bTime = b.last_message_timestamp ? new Date(b.last_message_timestamp).getTime() : 0;
    return bTime - aTime;
  });

  const safeOffset = Number.isFinite(Number(offset)) && Number(offset) > 0 ? Number(offset) : 0;
  const safeLimit = Number.isFinite(Number(limit)) && Number(limit) > 0 ? Number(limit) : 200;
  return {
    chats: filtered.slice(safeOffset, safeOffset + safeLimit),
    total_count: filtered.length,
  };
}

async function sendTextMessage(payload) {
  if (!client || !ready) {
    throw new Error("WhatsApp client is not ready");
  }

  const to = payload?.to;
  const message = payload?.message;
  const tenantId = payload?.tenant_id ?? null;
  const externalAccountId = String(payload?.external_account_id || "").trim();
  const whatsappEndpointId = payload?.whatsapp_endpoint_id ?? null;

  if (tenantId == null) {
    console.error(JSON.stringify({
      event: "whatsapp_outbound_send_missing_tenant_id",
      to: to || null,
      external_account_id: externalAccountId || null,
      whatsapp_endpoint_id: whatsappEndpointId,
      reason: "tenant_id is required for tenant-scoped CRM sends",
    }));
    throw new Error("WhatsApp payload is missing tenant_id");
  }

  if (!externalAccountId) {
    throw new Error("WhatsApp payload is missing external_account_id");
  }
  if (externalAccountId !== whatsappClientId) {
    throw new Error(`WhatsApp account id mismatch: requested ${externalAccountId} but this service is configured for ${whatsappClientId}`);
  }

  const chatId = normalizeRecipient(to);
  if (!chatId) {
    throw new Error("Invalid recipient phone number");
  }

  const identity = getCanonicalWhatsAppIdentity({
    direction: "outbound",
    whatsapp_chat_id: chatId,
    sender: null,
    recipient: to,
    to,
  }, { direction: "outbound" });

  pendingOutboundTenantByChatId.set(normalizeWhatsAppChatId(chatId), tenantId || null);
  if (identity.canonicalChatId) {
    pendingOutboundTenantByIdentityKey.set(identity.canonicalChatId, tenantId || null);
  }
  const sentMessage = await client.sendMessage(chatId, message);
  if (sentMessage?.id?._serialized) {
    pendingOutboundTenantByMessageId.set(sentMessage.id._serialized, tenantId || null);
    console.info(JSON.stringify({
      event: "whatsapp_outbound_send",
      message_id: sentMessage.id._serialized,
      chat_id: chatId,
      whatsapp_identity_key: identity.canonicalChatId,
      whatsapp_normalized_phone: identity.normalizedPhone,
      external_account_id: externalAccountId,
      tenant_id_received: tenantId || null,
      whatsapp_endpoint_id: whatsappEndpointId,
      resolution_source: "send_payload",
    }));
  }
  void forwardOutboundCapturedMessage(sentMessage, chatId, to, "sendMessage", tenantId).catch((error) => {
    console.error("Failed to forward outbound WhatsApp message to CRM:", error);
  });
  return {
    whatsapp_message_id: sentMessage?.id?._serialized || null,
    whatsapp_chat_id: chatId,
    whatsapp_identity_key: identity.canonicalChatId,
    whatsapp_normalized_phone: identity.normalizedPhone,
    tenant_id: tenantId || null,
    provider: "whatsapp-service",
    external_account_id: externalAccountId,
    whatsapp_endpoint_id: whatsappEndpointId,
  };
}

async function runHistoryBackfill(options = {}) {
  return backfillAllChats({ ...options, postSyncDelayMs: options.postSyncDelayMs ?? 0 });
}

async function runHistoryDebugSample({ chatCount = 3, messageLimit = 50, postSyncDelayMs = 1500 } = {}) {
  if (!client || !ready) {
    throw new Error("WhatsApp client is not ready");
  }

  const chats = typeof client.getChats === "function" ? await client.getChats() : [];
  const orderedChats = Array.isArray(chats)
    ? chats.slice().filter(isRelevantChat).sort((a, b) => String(getChatId(a) || "").localeCompare(String(getChatId(b) || ""))).slice(0, chatCount)
    : [];

  const samples = [];
  let totalMessages = 0;
  let inboundMessages = 0;
  let outboundMessages = 0;

  for (const chat of orderedChats) {
    try {
      const chatId = getChatId(chat);
      const chatName = getChatName(chat);
      const isGroup = Boolean(chat?.isGroup || String(chatId || "").endsWith("@g.us"));
      let syncHistorySuccess = false;
      let syncHistoryResult = null;
      if (typeof chat.syncHistory === "function") {
        syncHistoryResult = await chat.syncHistory();
        syncHistorySuccess = true;
        await sleep(postSyncDelayMs);
      }
      let messages = [];
      let fromMeMessages = [];
      try {
        messages = typeof chat.fetchMessages === "function" ? await chat.fetchMessages({ limit: messageLimit }) : [];
        fromMeMessages = typeof chat.fetchMessages === "function" ? await chat.fetchMessages({ limit: messageLimit, fromMe: true }) : [];
      } catch (error) {
        samples.push({
          chat_id: chatId,
          chat_name: chatName,
          isGroup,
          sync_history_success: syncHistorySuccess,
          sync_history_result: syncHistoryResult,
          fetch_error: error instanceof Error ? error.message : String(error),
        });
        continue;
      }
      const ordered = Array.isArray(messages) ? messages.slice().sort(sortBackfillMessages) : [];
      const orderedFromMe = Array.isArray(fromMeMessages) ? fromMeMessages.slice().sort(sortBackfillMessages) : [];
      const chatSamples = ordered.slice(0, 10).map((message) => ({
        whatsapp_message_id: message?.id?._serialized || null,
        timestamp: Number(message?.timestamp || 0),
        fromMe: Boolean(message?.fromMe),
      }));
      const fromMeSamples = orderedFromMe.slice(0, 10).map((message) => ({
        whatsapp_message_id: message?.id?._serialized || null,
        timestamp: Number(message?.timestamp || 0),
        fromMe: Boolean(message?.fromMe),
      }));
      const chatInbound = ordered.filter((message) => !message?.fromMe).length;
      const chatOutbound = ordered.filter((message) => message?.fromMe).length;
      totalMessages += ordered.length;
      inboundMessages += chatInbound;
      outboundMessages += chatOutbound;
      samples.push({
        chat_id: chatId,
        chat_name: chatName,
        isGroup,
        sync_history_success: syncHistorySuccess,
        sync_history_result: syncHistoryResult,
        fetch_messages_count: ordered.length,
        fetch_messages_inbound_count: chatInbound,
        fetch_messages_outbound_count: chatOutbound,
        fetch_messages_sample: chatSamples,
        fetch_messages_from_me_count: orderedFromMe.length,
        fetch_messages_from_me_sample: fromMeSamples,
      });
    } catch (error) {
      samples.push({
        chat_id: getChatId(chat),
        chat_name: getChatName(chat),
        isGroup: Boolean(chat?.isGroup || String(getChatId(chat) || "").endsWith("@g.us")),
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return {
    ready: Boolean(ready),
    total_chats_found: Array.isArray(chats) ? chats.length : 0,
    chats_scanned: orderedChats.length,
    total_messages: totalMessages,
    inbound_messages: inboundMessages,
    outbound_messages: outboundMessages,
    samples,
  };
}async function shutdownClient() {
  shuttingDown = true;
  ready = false;

  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  if (client) {
    try {
      await client.destroy();
    } catch (error) {
      console.warn("Failed to destroy WhatsApp client during shutdown:", error);
    }
  }

  client = null;
}

module.exports = {
  initializeClient,
  isReady,
  sendTextMessage,
  shutdownClient,
  runHistoryBackfill,
  backfillAllChats,
  runHistoryDebugSample,
  buildHistoryDedupeKey,
  sortBackfillMessages,
  listChats,
};




