const qrcode = require("qrcode-terminal");
const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const ChatFactory = require("whatsapp-web.js/src/factories/ChatFactory");

const {
  crmWebhookRouteToken,
  crmWebhookSecret,
  crmWebhookTimeoutMs,
  crmWebhookUrl,
  crmBackfillIdentitiesUrl,
  crmBackfillBatchUrl,
  crmBackfillBatchTimeoutMs,
  crmOutboundResolutionUrl,
  reconnectDelayMs,
  reconnectReplayGraceMs,
  reconnectBackoffMaxMs,
  reconnectLogoutThreshold,
  reconnectLogoutWindowMs,
  reconnectStatePath,
  readyStabilityMs,
  teardownGraceMs,
  whatsappClientId,
  whatsappWebVersion,
  whatsappHistoryBackfillBatchSize,
  whatsappHistoryBackfillLimit,
  whatsappHistoryBackfillEnabled,
  whatsappBackfillPaceMs,
  whatsappBackfillDedupeWindowMs,
  forwardedMessageCacheTtlMs,
  maxInboundMediaBytes,
} = require("./config");
const { resolveOutboundTenantOwnership } = require("./outboundResolution");
const { createForwardedMessageCache } = require("./forwardedMessageCache");
const { createTeardownWindow, getErrorMessage, isTransientPageError } = require("./transientErrors");
const { createReconnectStateStore } = require("./reconnectState");
const {
  applyLogout,
  computeReconnectDelayMs: computeReconnectDelayMsFor,
  shouldPauseAutoReconnect,
} = require("./logoutTracking");
const { buildWhatsAppIdentityCandidates, getCanonicalWhatsAppIdentity, normalizeWhatsAppChatId, normalizeWhatsAppPhone } = require("./whatsappIdentity");

// Grace window covering any teardown we knowingly started (LOGOUT, auth failure, forced restart,
// shutdown). See openTeardownWindow() for why a synchronous scope guard is not sufficient.
const teardownWindow = createTeardownWindow();

function openTeardownWindow(reason) {
  teardownWindow.open(teardownGraceMs);
  console.warn(
    `WhatsApp client teardown started (${reason}); page errors are non-fatal for the next ${teardownGraceMs}ms.`,
  );
}

function logIgnoredWhatsAppTransientNavigationError(prefix, error) {
  console.warn(prefix, getErrorMessage(error));
}

// whatsapp-web.js's own `framenavigated` listener (Client.js) re-calls inject() on every page
// navigation with no guard against an in-flight navigation destroying the execution context
// mid-evaluate. That throws inside an unguarded async event handler -> unhandled rejection or
// uncaught exception -> this whole process gets killed by Node, and systemd then kills the Chrome
// subprocess mid-write, corrupting the LocalAuth session and forcing a fresh QR scan every time.
//
// That crash path also silently defeated the repeated-LOGOUT backoff further down this file: the
// counters were in-memory, so every crash-restart reset them to 0 and the "pause auto-reconnect"
// threshold was never reached, no matter how often WhatsApp unlinked the device. Observed
// 2026-09-04 on both units as LOGOUT -> "Failed to add page binding ... already exists!" ->
// process.exit(1) -> systemd restart -> fresh QR.
//
// So there are two layers now:
//   1. Known-transient page errors are always ignored (see transientErrors.js).
//   2. While a teardown is in flight, ANY error is non-fatal. The client is already being rebuilt
//      by scheduleReconnect(), and staying alive preserves the very session that exiting corrupts.
// Outside a teardown an unrecognised error is still fatal, so real bugs stay loud.
function handleFatalErrorCandidate(kind, error) {
  if (isTransientPageError(error)) {
    logIgnoredWhatsAppTransientNavigationError("Ignored transient WhatsApp page-navigation race:", error);
    return;
  }

  if (teardownWindow.isOpen()) {
    console.error(`Ignored ${kind} during WhatsApp client teardown (not fatal, client is restarting):`, error);
    return;
  }

  console.error(`${kind}:`, error);
  process.exit(1);
}

process.on("unhandledRejection", (error) => {
  handleFatalErrorCandidate("Unhandled rejection", error);
});

process.on("uncaughtException", (error) => {
  handleFatalErrorCandidate("Uncaught exception", error);
});

let client = null;
let ready = false;
let initializingPromise = null;
let reconnectTimer = null;
let shuttingDown = false;
let startupBackfillTriggered = false;
let lastReadyAt = 0;
// Observability for the /admin/status and /admin/qr endpoints. The `qr` event is otherwise only
// printed to stdout (journal), which rotates away; persisting the latest QR and the last
// disconnect reason lets operators see connection state and re-link over HTTP without shell access.
let latestQr = null;
let latestQrAt = 0;
let lastDisconnect = null; // { reason, at, raw_state }
let lastAuthFailureAt = 0;
// Repeated-LOGOUT tracking for reconnect backoff. See config.reconnect* knobs.
// Rehydrated from disk so the pause threshold survives a restart: a counter that resets on every
// respawn can never reach the threshold when the restarts are themselves caused by the logouts.
const reconnectStateStore = createReconnectStateStore({ filePath: reconnectStatePath });
const persistedReconnectState = reconnectStateStore.load();
let consecutiveLogoutCount = persistedReconnectState.consecutiveLogoutCount;
let lastLogoutAt = persistedReconnectState.lastLogoutAt;
let autoReconnectPaused = persistedReconnectState.autoReconnectPaused;

if (consecutiveLogoutCount > 0 || autoReconnectPaused) {
  console.warn(
    `Restored WhatsApp reconnect state: ${consecutiveLogoutCount} recent LOGOUT(s), ` +
      `auto_reconnect_paused=${autoReconnectPaused}.` +
      (autoReconnectPaused ? " POST /admin/reconnect to resume once the number has rested." : ""),
  );
}

function persistReconnectState() {
  reconnectStateStore.save({ consecutiveLogoutCount, lastLogoutAt, autoReconnectPaused });
}

// Fires once a session has held for readyStabilityMs, which is the only thing that actually proves
// WhatsApp accepted this device. See the `ready` handler for why reaching ready is not enough.
let logoutStateResetTimer = null;

function clearLogoutStateResetTimer() {
  if (logoutStateResetTimer) {
    clearTimeout(logoutStateResetTimer);
    logoutStateResetTimer = null;
  }
}

function scheduleLogoutStateReset() {
  clearLogoutStateResetTimer();
  if (consecutiveLogoutCount === 0) {
    return;
  }

  logoutStateResetTimer = setTimeout(() => {
    logoutStateResetTimer = null;
    consecutiveLogoutCount = 0;
    lastLogoutAt = 0;
    persistReconnectState();
    console.log(`WhatsApp session held for ${readyStabilityMs}ms; cleared the repeated-LOGOUT backoff state.`);
  }, readyStabilityMs);

  // Bookkeeping only - must never be the reason the process stays alive.
  if (typeof logoutStateResetTimer.unref === "function") {
    logoutStateResetTimer.unref();
  }
}
const forwardedMessages = createForwardedMessageCache({ ttlMs: forwardedMessageCacheTtlMs });
const pendingOutboundTenantByMessageId = new Map();
const pendingOutboundTenantByChatId = new Map();
const pendingOutboundTenantByIdentityKey = new Map();
let outboundCaptureCount = 0;

function getChatId(chat) {
  return chat?.id?._serialized || chat?.id?.serialized || chat?.id || null;
}

function isWithinReconnectGrace() {
  return Date.now() - lastReadyAt < reconnectReplayGraceMs;
}

// whatsapp-web.js's own window.WWebJS.getChatModel() resolves a chat's last-message preview via
// Msg.get()/Msg.getMessagesById(chat.lastReceivedKey._serialized) with no guard. For a fixed,
// reproducible set of @lid contacts on this account, that lookup throws a DataError from
// WhatsApp Web's own IndexedDB-backed message store ("bulkGet on Table: message" with an empty
// key) - confirmed via /admin/debug/chat-model, which isolates getChatModel step by step. Because
// getChatModel has no try/catch of its own, that one preview lookup fails the entire chat model,
// which in turn fails whatsapp-web.js's own Client#getChats()/getChatById() (both build models via
// Promise.all/getChatModel), taking every other chat down with it. Rebuild the same model
// ourselves with that one step guarded - the preview is optional; the chat itself is not.
async function fetchChatModelsSafe(activeClient, { targetChatId = null, wrap = false } = {}) {
  if (!activeClient) {
    return { chats: [], failed: [] };
  }

  if (typeof activeClient.pupPage?.evaluate === "function") {
    const { models, failed } = await activeClient.pupPage.evaluate(async (targetChatId) => {
      async function buildModel(chat) {
        const model = chat.serialize();
        model.isGroup = false;
        model.isMuted = chat.mute?.expiration !== 0;
        model.formattedTitle = chat.formattedTitle;

        if (chat.groupMetadata) {
          model.isGroup = true;
          try {
            const chatWid = window.require("WAWebWidFactory").createWid(chat.id._serialized);
            const groupMetadata =
              window.require("WAWebCollections").GroupMetadata ||
              window.require("WAWebCollections").WAWebGroupMetadataCollection;
            await groupMetadata.update(chatWid);
            const { toPn } = window.require("WAWebLidMigrationUtils");
            const serializedMetadata = chat.groupMetadata.serialize();
            for (const p of serializedMetadata.participants || []) {
              p.id = toPn(p.id) ?? p.id;
            }
            model.groupMetadata = serializedMetadata;
            model.isReadOnly = chat.groupMetadata.announce;
          } catch (ignoredError) {
            // Group metadata occasionally can't be resolved; keep the chat usable without it.
          }
        }

        model.lastMessage = null;
        if (model.msgs && model.msgs.length) {
          try {
            const lastMessage = chat.lastReceivedKey
              ? window.require("WAWebCollections").Msg.get(chat.lastReceivedKey._serialized) ||
                (
                  await window
                    .require("WAWebCollections")
                    .Msg.getMessagesById([chat.lastReceivedKey._serialized])
                )?.messages?.[0]
              : null;
            lastMessage && (model.lastMessage = window.WWebJS.getMessageModel(lastMessage));
          } catch (ignoredError) {
            // The known DataError: WhatsApp Web's message store can't resolve this chat's last
            // message. The preview is a nice-to-have - skip it rather than losing the whole chat.
          }
        }

        delete model.msgs;
        delete model.msgUnsyncedButtonReplyMsgs;
        delete model.unsyncedButtonReplies;
        return model;
      }

      const models = [];
      const failed = [];

      if (targetChatId) {
        try {
          const chatWid = window.require("WAWebWidFactory").createWid(targetChatId);
          const chat =
            window.require("WAWebCollections").Chat.get(chatWid) ||
            (await window.require("WAWebFindChatAction").findOrCreateLatestChat(chatWid))?.chat;
          if (chat) {
            models.push(await buildModel(chat));
          }
        } catch (error) {
          failed.push({
            id: targetChatId,
            message: error && error.message ? String(error.message) : String(error),
          });
        }
        return { models, failed };
      }

      const rawChats = window.require("WAWebCollections").Chat.getModelsArray();
      for (const chat of rawChats) {
        try {
          models.push(await buildModel(chat));
        } catch (error) {
          failed.push({
            id: chat?.id?._serialized || null,
            message: error && error.message ? String(error.message) : String(error),
          });
        }
      }
      return { models, failed };
    }, targetChatId);

    for (const failure of failed) {
      console.warn(JSON.stringify({
        event: "whatsapp_chat_model_build_failed",
        chat_id: failure.id,
        error: failure.message,
      }));
    }

    const chats = wrap ? models.map((data) => ChatFactory.create(activeClient, data)) : models;
    return { chats, failed };
  }

  // Test doubles don't expose a real pupPage - preserve the prior, simpler behavior exactly.
  if (targetChatId && typeof activeClient.getChatById === "function") {
    let targetChat = null;
    try {
      targetChat = await activeClient.getChatById(targetChatId);
    } catch (error) {
      console.warn(JSON.stringify({
        event: "whatsapp_history_get_chat_by_id_failed",
        chat_id: targetChatId,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
    return { chats: targetChat ? [targetChat] : [], failed: [] };
  }

  const chats = typeof activeClient.getChats === "function" ? await activeClient.getChats() : [];
  let filteredChats = Array.isArray(chats) ? chats : [];
  if (targetChatId) {
    filteredChats = filteredChats.filter((chat) => String(getChatId(chat) || "") === targetChatId);
  }
  return { chats: filteredChats, failed: [] };
}

// One-off diagnostic: window.WWebJS.getChatModel() is a single opaque call from our side, and
// its errors serialize across the puppeteer bridge as a bare minified identifier (e.g. "r") with
// no useful message. This reimplements it step by step so we can see exactly which sub-step
// throws for a given chat, and with what real error name/message/stack, instead of a dead end.
async function debugChatModelBuild(chatId) {
  if (!client || !ready) {
    throw new Error("WhatsApp client is not ready");
  }
  const targetChatId = String(chatId || "").trim();
  if (!targetChatId) {
    throw new Error("chatId is required");
  }

  return client.pupPage.evaluate(async (chatId) => {
    function describeError(error) {
      const details = {
        name: error?.name ?? null,
        message: error?.message ?? String(error),
        stack: error?.stack ?? null,
      };
      try {
        for (const key of Object.getOwnPropertyNames(error || {})) {
          if (!(key in details)) details[key] = error[key];
        }
      } catch (ignored) {
        // best-effort only
      }
      return details;
    }

    const steps = [];
    let chatWid;
    try {
      chatWid = window.require("WAWebWidFactory").createWid(chatId);
      steps.push({ step: "createWid", ok: true });
    } catch (error) {
      steps.push({ step: "createWid", ok: false, error: describeError(error) });
      return { steps, chatFound: false };
    }

    let chat;
    try {
      chat =
        window.require("WAWebCollections").Chat.get(chatWid) ||
        (await window.require("WAWebFindChatAction").findOrCreateLatestChat(chatWid))?.chat;
      steps.push({ step: "resolveChat", ok: true, found: Boolean(chat) });
    } catch (error) {
      steps.push({ step: "resolveChat", ok: false, error: describeError(error) });
      return { steps, chatFound: false };
    }

    if (!chat) {
      return { steps, chatFound: false };
    }

    try {
      chat.serialize();
      steps.push({ step: "serialize", ok: true });
    } catch (error) {
      steps.push({ step: "serialize", ok: false, error: describeError(error) });
    }

    try {
      const formattedTitle = chat.formattedTitle;
      steps.push({ step: "formattedTitle", ok: true, value: formattedTitle || null });
    } catch (error) {
      steps.push({ step: "formattedTitle", ok: false, error: describeError(error) });
    }

    const hasGroupMetadata = Boolean(chat.groupMetadata);
    steps.push({ step: "groupMetadataPresence", ok: true, value: hasGroupMetadata });
    if (hasGroupMetadata) {
      try {
        const groupChatWid = window.require("WAWebWidFactory").createWid(chat.id._serialized);
        const groupMetadata =
          window.require("WAWebCollections").GroupMetadata ||
          window.require("WAWebCollections").WAWebGroupMetadataCollection;
        await groupMetadata.update(groupChatWid);
        steps.push({ step: "groupMetadata.update", ok: true });
      } catch (error) {
        steps.push({ step: "groupMetadata.update", ok: false, error: describeError(error) });
      }
      try {
        const { toPn } = window.require("WAWebLidMigrationUtils");
        const serializedMetadata = chat.groupMetadata.serialize();
        for (const p of serializedMetadata.participants || []) {
          toPn(p.id);
        }
        steps.push({ step: "groupMetadata.serialize+toPn", ok: true });
      } catch (error) {
        steps.push({ step: "groupMetadata.serialize+toPn", ok: false, error: describeError(error) });
      }
    }

    const hasLastReceivedKey = Boolean(chat.lastReceivedKey);
    steps.push({ step: "lastReceivedKeyPresence", ok: true, value: hasLastReceivedKey });
    if (hasLastReceivedKey) {
      try {
        const lastMessage =
          window.require("WAWebCollections").Msg.get(chat.lastReceivedKey._serialized) ||
          (await window.require("WAWebCollections").Msg.getMessagesById([chat.lastReceivedKey._serialized]))?.messages?.[0];
        steps.push({ step: "lastMessageLookup", ok: true, found: Boolean(lastMessage) });
      } catch (error) {
        steps.push({ step: "lastMessageLookup", ok: false, error: describeError(error) });
      }
    }

    return {
      steps,
      chatFound: true,
      chatId: chat?.id?._serialized || null,
      isGroup: Boolean(chat?.groupMetadata),
    };
  }, targetChatId);
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
    return { found: false, resolution_strategy: "unconfigured", transient: false };
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
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), crmWebhookTimeoutMs);
  try {
    const response = await fetch(url, {
      method: "GET",
      headers,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      // 429/5xx are genuinely transient (worth one retry); other 4xx are not - retrying a
      // malformed/unauthorized request won't produce a different answer.
      const transient = response.status === 429 || response.status >= 500;
      return {
        ...(payload || {}),
        found: false,
        resolution_strategy: (payload && payload.resolution_strategy) || `http_${response.status}`,
        transient,
      };
    }
    return payload || { found: false, resolution_strategy: "empty_response", transient: false };
  } catch (error) {
    const isTimeout = error instanceof Error && error.name === "AbortError";
    return {
      found: false,
      resolution_strategy: isTimeout ? "timeout" : "lookup_error",
      transient: true,
      error: error instanceof Error ? error.message : String(error),
    };
  } finally {
    clearTimeout(timeout);
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

// Only ever called from the live inbound path. The history/backfill path must NOT download
// media: backfillAllChats forwards in batches of 200 chats' worth of messages, so downloading
// there would mean thousands of WhatsApp Web round trips and multi-hundred-MB batch bodies.
// The guard is the call site, deliberately not a `source` check on the payload - that field was
// previously hard-coded to "history" here and silently broke source-gated logic.
async function downloadMediaSafely(message) {
  if (!message?.hasMedia) {
    return null;
  }
  try {
    const media = await message.downloadMedia();
    // downloadMedia resolves undefined for expired or undecryptable media rather than throwing.
    if (!media?.data) {
      return null;
    }
    const sizeBytes = Buffer.byteLength(media.data, "base64");
    if (sizeBytes > maxInboundMediaBytes) {
      console.warn(
        `Skipping inbound WhatsApp media above the size cap: ${sizeBytes} bytes > ${maxInboundMediaBytes}`,
      );
      return null;
    }
    return {
      filename: media.filename || null,
      mime_type: media.mimetype || null,
      size_bytes: sizeBytes,
      data_base64: media.data,
    };
  } catch (error) {
    console.warn("Failed to download inbound WhatsApp media:", error);
    return null;
  }
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
  // A media message with no caption has no text of its own, so fall back to the filename
  // before the generic "[Image]"-style placeholder that extractText would otherwise return.
  const media = overrides.media || null;
  let text = extractText(message);
  if (!text && media) {
    text = media.filename ? `[File] ${media.filename}` : "[File]";
  }
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
    // Always present so the CRM webhook can iterate it unconditionally; only the live inbound
    // path ever populates it (see downloadMediaSafely).
    attachments: media
      ? [
          {
            filename: media.filename,
            mime_type: media.mime_type,
            size_bytes: media.size_bytes,
            data_base64: media.data_base64,
          },
        ]
      : [],
  };
}

async function forwardCrmMessage(payload, contextLabel, options = {}) {
  if (!crmWebhookUrl) {
    console.warn(`CRM WhatsApp webhook URL is not configured; ${contextLabel} messages will not be forwarded.`);
    return false;
  }

  // The forwardedMessages cache only tracks "did this process already send this message id",
  // not "does the CRM still have it" - it can't see a relink or a CRM-side data reset that
  // happened without restarting this service. History/backfill forwarding relies on the CRM's
  // own provider_message_id dedup instead (see _find_existing_inbound_whatsapp_communication),
  // so it opts out of this cache to make "resync full history" actually able to redeliver.
  const messageId = payload.whatsapp_message_id || null;
  const dedupeEnabled = !options.skipForwardedCache && Boolean(messageId);

  if (dedupeEnabled) {
    if (forwardedMessages.isForwarded(messageId)) {
      console.info(
        "Skipping duplicate %s WhatsApp message for CRM forwarding: message_id=%s",
        contextLabel,
        messageId,
      );
      return false;
    }
    // Claim synchronously (before the first await below) so the explicit sendMessage path and
    // the message_create listener - which can both observe the same outbound message - can't
    // both win this race and double-post to the CRM webhook.
    if (!forwardedMessages.claimInFlight(messageId)) {
      console.info(
        "Skipping in-flight duplicate %s WhatsApp message for CRM forwarding: message_id=%s",
        contextLabel,
        messageId,
      );
      return false;
    }
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

    if (messageId) {
      forwardedMessages.markForwarded(messageId);
    }
    return true;
  } finally {
    clearTimeout(timeout);
    if (dedupeEnabled) {
      forwardedMessages.releaseInFlight(messageId);
    }
  }
}

// History backfill used to forward every historical message as its own sequential
// forwardCrmMessage() call, so a chat with a few thousand messages meant a few thousand
// serial HTTP round trips — this is what made "resync" take minutes to tens of minutes.
// This sends a whole chunk of history payloads in a single request to the CRM's batch
// endpoint, which applies the exact same per-message routing/dedup/persistence logic
// in-process instead of over the network.
async function forwardCrmMessageBatch(payloads) {
  if (!crmBackfillBatchUrl) {
    console.warn("CRM WhatsApp backfill batch URL is not configured; history messages will not be forwarded.");
    return { processed: 0, failed: 0 };
  }
  if (!payloads.length) {
    return { processed: 0, failed: 0 };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), crmBackfillBatchTimeoutMs);

  try {
    console.info(
      "Forwarding WhatsApp history batch to CRM: count=%s chat_id=%s client_id=%s",
      payloads.length,
      payloads[0]?.whatsapp_chat_id,
      payloads[0]?.whatsapp_client_id,
    );

    const response = await fetch(crmBackfillBatchUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(crmWebhookRouteToken ? { "X-Webhook-Token": crmWebhookRouteToken } : {}),
        ...(crmWebhookSecret ? { "X-Webhook-Secret": crmWebhookSecret } : {}),
      },
      body: JSON.stringify({ messages: payloads }),
      signal: controller.signal,
    });

    const responseBody = await response.json().catch(() => null);
    if (!response.ok) {
      const responseText = responseBody ? JSON.stringify(responseBody) : "";
      throw new Error(`CRM backfill batch webhook responded with ${response.status}${responseText ? `: ${responseText}` : ""}`);
    }

    return {
      processed: Number(responseBody?.processed || 0),
      failed: Number(responseBody?.failed || 0),
    };
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

  // Downloaded before the empty-text bail so a caption-less media message still gets through:
  // buildCrmPayload derives placeholder text from the media's filename when there's no caption.
  const media = await downloadMediaSafely(message);
  const text = extractText(message);
  if (!text && !media) {
    return false;
  }

  const payload = buildCrmPayload(message, "inbound", {
    sender: message?.author || message?.from || null,
    whatsapp_chat_id: message?.from || null,
    media,
    source: isWithinReconnectGrace() ? "history" : undefined,
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
    source: isWithinReconnectGrace() ? "history" : undefined,
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
  // The per-message entry set at send time (one per sent message) must be released here too --
  // unlike the chat/identity maps it was never deleted, so it grew unbounded for the life of the
  // process (one entry per outbound message forever).
  if (message?.id?._serialized) {
    pendingOutboundTenantByMessageId.delete(message.id._serialized);
  }
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
  let digits = value.replace(/\D+/g, "");
  if (!digits) {
    return null;
  }
  // A leading "00" is the international dialing exit code many people use in place of "+"
  // (e.g. "0039..." for an Italian number instead of "+39..."). WhatsApp ids never carry it -
  // left in place, a valid number becomes a malformed WhatsApp id that the send silently fails
  // or crashes on instead of a clean "not registered" result.
  if (digits.length > 2 && digits.startsWith("00")) {
    digits = digits.slice(2);
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
    const fetched = typeof chat.fetchMessages === "function" ? await chat.fetchMessages({ limit }) : [];
    // fetchMessages() without fromMe alone can miss messages sent from another linked device
    // (phone, another PC) that never round-tripped through this session's local store. The
    // fromMe: true query path retrieves them separately, so merge and dedupe both results.
    const fromMeFetched = typeof chat.fetchMessages === "function" ? await chat.fetchMessages({ limit, fromMe: true }) : [];
    const seenMergeIds = new Set();
    for (const message of [...(Array.isArray(fetched) ? fetched : []), ...(Array.isArray(fromMeFetched) ? fromMeFetched : [])]) {
      const mergeId = message?.id?._serialized || buildHistoryDedupeKey(message, chatId, message?.fromMe ? "outbound" : "inbound");
      if (!seenMergeIds.has(mergeId)) {
        seenMergeIds.add(mergeId);
        messages.push(message);
      }
    }
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
  const payloads = [];

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

    payloads.push(
      buildCrmPayload(message, direction, {
        to: direction === "outbound" ? normalizeRecipient(chat?.id?.user || chat?.id || message?.to || message?.from) : null,
        sender: message?.author || message?.from || null,
        whatsapp_chat_id: chat?.id?._serialized || chat?.id || message?.from || message?.to || null,
        whatsapp_message_id: whatsappMessageId,
        source: "history",
      }),
    );
  }

  // Forwarding each historical message as its own sequential HTTP request (the original
  // design) made a resync of a chat with thousands of messages take minutes to tens of
  // minutes — nearly all of that time was network/request-dispatch overhead, not actual
  // work. Sending chunks of payloads to the batch endpoint collapses that to one round
  // trip per chunk while the CRM applies identical per-message routing/dedup logic.
  const batchSize = Math.max(1, whatsappHistoryBackfillBatchSize);
  for (let start = 0; start < payloads.length; start += batchSize) {
    const chunk = payloads.slice(start, start + batchSize);
    try {
      const result = await forwardCrmMessageBatch(chunk);
      imported += result.processed;
      failed += result.failed;
    } catch (error) {
      failed += chunk.length;
      console.error(JSON.stringify({
        event: "whatsapp_history_import_batch_failure",
        ...logBase,
        chunk_size: chunk.length,
        chunk_start: start,
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

  const targetChatId = chatId ? String(chatId).trim() : null;

  const { chats } = await fetchChatModelsSafe(activeClient, { targetChatId, wrap: true });
  const orderedChats = Array.isArray(chats)
    ? chats.slice().sort((a, b) => String(getChatId(a) || "").localeCompare(String(getChatId(b) || "")))
    : [];

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
    // Go through runHistoryBackfill (not backfillAllChats directly) so the startup sweep is
    // serialized and paced alongside any CRM-triggered backfills instead of racing them.
    const result = await runHistoryBackfill({ limit: whatsappHistoryBackfillLimit, all: false });
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
    latestQr = qr;
    latestQrAt = Date.now();
    console.log("Scan this QR code with WhatsApp to connect the service:");
    qrcode.generate(qr, { small: true });
  });

  nextClient.on("authenticated", () => {
    console.log("WhatsApp session authenticated.");
  });

  nextClient.on("ready", () => {
    ready = true;
    lastReadyAt = Date.now();
    // The QR is consumed once the session is linked; drop it so /admin/qr reports "already linked".
    latestQr = null;
    // Linking succeeded, so auto-reconnect is allowed again (reaching ready while paused means a
    // human re-scanned the QR or called /admin/reconnect).
    autoReconnectPaused = false;
    // But do NOT clear the repeated-LOGOUT counters here. In the observed loop the client reaches
    // ready and is force-unlinked ~5 minutes later, so `ready` is not evidence WhatsApp accepted
    // the device - and clearing on every ready is what let the flap run indefinitely without the
    // pause threshold ever being reached. Only a session that survives readyStabilityMs counts.
    persistReconnectState();
    scheduleLogoutStateReset();
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
    // One bounded retry (not a full 10x rerun) to cover real eventual consistency - e.g. the
    // CRM hasn't committed a durable link yet at the instant this event fires. A normal,
    // durably-confirmed "not found" is not retried here; resolveOutboundTenantOwnership already
    // handles per-candidate transient retries (network error/timeout/429/5xx) on its own.
    const attemptForward = async (remainingAttempts = 1) => {
      if (messageId && forwardedMessages.isForwarded(messageId)) {
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
        await sleep(1000);
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
    // Guard the outer call: a rejection from resolveOutboundTenantOwnership/lookupDurable that
    // escapes the inner forward catch would otherwise be an unhandledRejection, which this
    // process turns into process.exit(1). Mirror the sibling `message` handler's .catch().
    void attemptForward().catch((error) => {
      console.error("Failed to resolve/forward outbound WhatsApp message to CRM:", error);
    });
  });

  nextClient.on("auth_failure", (message) => {
    ready = false;
    lastAuthFailureAt = Date.now();
    console.error(`WhatsApp authentication failed: ${message}`);
    openTeardownWindow("auth_failure");
    scheduleReconnect();
  });

  nextClient.on("disconnected", (reason) => {
    ready = false;
    const reasonStr = reason == null ? null : String(reason);
    const at = Date.now();
    // The session did not survive long enough to count as stable, so the LOGOUT history stands.
    clearLogoutStateResetTimer();
    // The page is already being torn down by WhatsApp at this point; everything Puppeteer throws
    // from here until the reconnect settles is expected, and must not kill the process.
    openTeardownWindow(`disconnected: ${reasonStr}`);
    // Persist the reason (e.g. "LOGOUT") so /admin/status can explain why the client is not ready
    // after the journal has rotated. A LOGOUT means the linked device was removed and a fresh QR
    // scan is required; a transient reason usually recovers via scheduleReconnect().
    lastDisconnect = { reason: reasonStr, at, raw_state: null };
    console.warn(`WhatsApp client disconnected: ${reasonStr}`);
    // Best-effort: read the raw page-side WhatsApp state so a future logout tells us CONFLICT vs a
    // true LOGOUT vs a transient navigation, instead of only the generic wwebjs reason. The page
    // has usually already navigated on logout so this frequently returns null; that's expected.
    void captureDisconnectState(nextClient, at).catch(() => {});

    // Track rapid, repeated LOGOUTs (WhatsApp force-unlinking the device). Reset the counter once a
    // window elapses without one, so isolated logouts still reconnect promptly.
    if (reasonStr === "LOGOUT") {
      ({ consecutiveLogoutCount, lastLogoutAt } = applyLogout(
        { consecutiveLogoutCount, lastLogoutAt },
        at,
        reconnectLogoutWindowMs,
      ));

      if (shouldPauseAutoReconnect(consecutiveLogoutCount, reconnectLogoutThreshold)) {
        autoReconnectPaused = true;
        persistReconnectState();
        console.error(
          `WhatsApp client hit ${consecutiveLogoutCount} consecutive LOGOUTs, each within ` +
            `${reconnectLogoutWindowMs}ms of the previous; ` +
            "pausing auto-reconnect to avoid thrashing a device WhatsApp keeps rejecting. " +
            "Re-scan the QR, or POST /admin/reconnect once the number has rested, to resume.",
        );
        return;
      }

      persistReconnectState();
    }

    scheduleReconnect(computeReconnectDelayMs());
  });
}

// Non-LOGOUT disconnects keep the base delay because consecutiveLogoutCount stays 0 for them.
function computeReconnectDelayMs() {
  return computeReconnectDelayMsFor(consecutiveLogoutCount, reconnectDelayMs, reconnectBackoffMaxMs);
}

async function captureDisconnectState(activeClient, disconnectedAt) {
  try {
    const page = activeClient?.pupPage;
    if (!page) {
      return;
    }
    const state = await page.evaluate(() => {
      try {
        const store = window.Store;
        if (!store) {
          return null;
        }
        if (store.AppState && store.AppState.state != null) {
          return store.AppState.state;
        }
        if (store.State && store.State.default && store.State.default.state != null) {
          return store.State.default.state;
        }
        return null;
      } catch (error) {
        return null;
      }
    });
    // Only annotate if this is still the same disconnect we were called for (avoid clobbering a
    // newer disconnect/reconnect that raced ahead while evaluate() was pending).
    if (lastDisconnect && lastDisconnect.at === disconnectedAt) {
      lastDisconnect.raw_state = state == null ? null : String(state);
    }
  } catch (error) {
    // The execution context is routinely destroyed by the logout navigation; diagnostics here are
    // strictly best-effort, so swallow the (known-transient) failure.
  }
}

// Clears a paused auto-reconnect (see the LOGOUT-threshold guard above) and kicks off a reconnect
// attempt. Exposed via POST /admin/reconnect so a human can resume without a full service restart.
function resumeReconnect() {
  const wasPaused = autoReconnectPaused;
  autoReconnectPaused = false;
  consecutiveLogoutCount = 0;
  lastLogoutAt = 0;
  persistReconnectState();
  scheduleReconnect(0);
  return { resumed: wasPaused };
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
    webVersion: whatsappWebVersion,
    webVersionCache: {
      type: "local",
      strict: true,
    },
  });

  attachClientEvents(nextClient);
  return nextClient;
}

function scheduleReconnect(delayMs) {
  if (shuttingDown || reconnectTimer || autoReconnectPaused) {
    return;
  }

  const delay = Number.isFinite(delayMs) ? Math.max(0, delayMs) : reconnectDelayMs;
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    try {
      await initializeClient(true);
    } catch (error) {
      console.error("WhatsApp reconnect attempt failed:", error);
      scheduleReconnect(computeReconnectDelayMs());
    }
  }, delay);
}

async function initializeClient(forceRestart = false) {
  if (initializingPromise) {
    return initializingPromise;
  }

  if (client && forceRestart) {
    // destroy() closes the CDP target out from under any in-flight page work, which is a reliable
    // source of async "Target closed"/"Protocol error" rejections landing after this returns.
    openTeardownWindow("client restart");
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

// Connection state for the /admin/status endpoint. Deliberately omits the raw QR string so the
// status view is safe to expose more freely than the QR itself.
function getConnectionStatus() {
  return {
    ready,
    client_id: whatsappClientId || null,
    last_ready_at: lastReadyAt ? new Date(lastReadyAt).toISOString() : null,
    last_disconnect: lastDisconnect
      ? {
          reason: lastDisconnect.reason,
          at: new Date(lastDisconnect.at).toISOString(),
          raw_state: lastDisconnect.raw_state ?? null,
        }
      : null,
    last_auth_failure_at: lastAuthFailureAt ? new Date(lastAuthFailureAt).toISOString() : null,
    consecutive_logouts: consecutiveLogoutCount,
    auto_reconnect_paused: autoReconnectPaused,
    // Whether consecutive_logouts survives a restart. If false, the auto-reconnect pause threshold
    // can be silently reset by a respawn (the failure mode that hid the LOGOUT loop until now).
    reconnect_state_persisted: Boolean(reconnectStateStore.filePath),
    // True while a known teardown is in flight, during which page errors are deliberately non-fatal.
    teardown_window_open: teardownWindow.isOpen(),
    has_qr: Boolean(latestQr) && !ready,
    qr_age_ms: latestQr && !ready && latestQrAt ? Date.now() - latestQrAt : null,
  };
}

// Latest QR string for the /admin/qr endpoint. Returns null qr once the client is ready (linked).
function getLatestQr() {
  if (ready || !latestQr) {
    return { qr: null, generated_at: null };
  }
  return { qr: latestQr, generated_at: latestQrAt ? new Date(latestQrAt).toISOString() : null };
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

  const { chats } = await fetchChatModelsSafe(activeClient);
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
  const activeClient = payload?.clientOverride || client;
  const isClientReady = payload?.readyOverride ?? ready;
  if (!activeClient || !isClientReady) {
    throw new Error("WhatsApp client is not ready");
  }

  const to = payload?.to;
  const message = payload?.message;
  const tenantId = payload?.tenant_id ?? null;
  const externalAccountId = String(payload?.external_account_id || "").trim();
  const whatsappEndpointId = payload?.whatsapp_endpoint_id ?? null;
  const attachments = Array.isArray(payload?.attachments) ? payload.attachments : [];

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

  // Opt-in only: the normal reply-to-linked-chat path never sets this, since it's sending
  // into a chat that's already proven to exist. It's for the "first message to a brand-new
  // number" flow, where a mistyped or non-WhatsApp number would otherwise silently create a
  // channel/link to nowhere.
  if (payload?.require_registered_recipient === true) {
    const numberId = await activeClient.getNumberId(chatId);
    if (!numberId) {
      const error = new Error("Recipient is not a registered WhatsApp user");
      error.statusCode = 422;
      throw error;
    }
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

  async function warmUpRecipientIdentity() {
    if (typeof activeClient.getContactById === "function") {
      try {
        await activeClient.getContactById(chatId);
        return;
      } catch (error) {
        console.warn(JSON.stringify({
          event: "whatsapp_outbound_identity_warmup_contact_failed",
          chat_id: chatId,
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    }

    if (typeof activeClient.getChatById === "function") {
      try {
        await activeClient.getChatById(chatId);
      } catch (error) {
        console.warn(JSON.stringify({
          event: "whatsapp_outbound_identity_warmup_chat_failed",
          chat_id: chatId,
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    }
  }

  const isNoLidForUserError = (error) => {
    const message = error instanceof Error ? error.message : String(error);
    return message.includes("No LID for user");
  };

  async function sendOnce() {
    const sent = [];

    // A caption only renders on the media it rides along with, so it's only used when there is
    // exactly one attachment. With several, the text would be buried in the first item (and
    // some types - audio/ptt, stickers - drop captions entirely), so it goes out on its own.
    if (attachments.length === 1 && message) {
      const attachment = attachments[0];
      const media = new MessageMedia(attachment.mime_type, attachment.data_base64, attachment.filename);
      sent.push({
        message: await activeClient.sendMessage(chatId, media, { caption: message }),
        kind: "media",
        attachment_index: 0,
      });
    } else {
      if (message) {
        sent.push({ message: await activeClient.sendMessage(chatId, message), kind: "text", attachment_index: null });
      }
      for (let index = 0; index < attachments.length; index += 1) {
        const attachment = attachments[index];
        const media = new MessageMedia(attachment.mime_type, attachment.data_base64, attachment.filename);
        sent.push({
          message: await activeClient.sendMessage(chatId, media),
          kind: "media",
          attachment_index: index,
        });
      }
    }

    return sent;
  }

  const firstMessageFlow = payload?.require_registered_recipient === true;
  let sent;

  if (firstMessageFlow) {
    await warmUpRecipientIdentity();
  }

  try {
    sent = await sendOnce();
  } catch (error) {
    if (!firstMessageFlow || !isNoLidForUserError(error)) {
      throw error;
    }

    await warmUpRecipientIdentity();
    sent = await sendOnce();
  }


  // WhatsApp resolves the chat we actually land in independently of the id we requested by -
  // a contact whose account uses @lid may still be reached by sending to their plain @c.us
  // number, but the message (and every future inbound reply) is filed under the @lid chat.
  // `chatId` is only our best guess before sending; `message.id.remote` on the sent message is
  // what WhatsApp actually resolved it to, and is what must be persisted/matched against.
  const firstSentMessage = sent.length > 0 ? sent[0].message : null;
  const resolvedChatId = firstSentMessage?.id?.remote || chatId;
  const resolvedIdentity = resolvedChatId === chatId
    ? identity
    : getCanonicalWhatsAppIdentity({
      direction: "outbound",
      whatsapp_chat_id: resolvedChatId,
      sender: null,
      recipient: to,
      to,
    }, { direction: "outbound" });

  if (resolvedChatId !== chatId) {
    pendingOutboundTenantByChatId.set(normalizeWhatsAppChatId(resolvedChatId), tenantId || null);
    if (resolvedIdentity.canonicalChatId) {
      pendingOutboundTenantByIdentityKey.set(resolvedIdentity.canonicalChatId, tenantId || null);
    }
    console.info(JSON.stringify({
      event: "whatsapp_outbound_chat_id_resolved",
      requested_chat_id: chatId,
      resolved_chat_id: resolvedChatId,
      external_account_id: externalAccountId,
      tenant_id_received: tenantId || null,
    }));
  }

  // Every sent message must register its own pending-tenant entry and be forwarded: messages
  // 2..N would otherwise come back through the message_create listener with no tenant and be
  // dropped by outbound resolution.
  for (const entry of sent) {
    const sentMessage = entry.message;
    if (sentMessage?.id?._serialized) {
      pendingOutboundTenantByMessageId.set(sentMessage.id._serialized, tenantId || null);
      console.info(JSON.stringify({
        event: "whatsapp_outbound_send",
        message_id: sentMessage.id._serialized,
        chat_id: resolvedChatId,
        whatsapp_identity_key: resolvedIdentity.canonicalChatId,
        whatsapp_normalized_phone: resolvedIdentity.normalizedPhone,
        external_account_id: externalAccountId,
        tenant_id_received: tenantId || null,
        whatsapp_endpoint_id: whatsappEndpointId,
        resolution_source: "send_payload",
        kind: entry.kind,
      }));
    }
    void forwardOutboundCapturedMessage(sentMessage, resolvedChatId, to, "sendMessage", tenantId).catch((error) => {
      console.error("Failed to forward outbound WhatsApp message to CRM:", error);
    });
  }

  // Best-effort only, and only for the first-message flow (the reply flow already knows the
  // chat's display name from its existing link) - a failure here must never break the send
  // itself, so any error is swallowed and just leaves the name unset.
  let contactName = null;
  if (payload?.require_registered_recipient === true) {
    try {
      const contact = await activeClient.getContactById(resolvedChatId);
      contactName = contact?.pushname || contact?.verifiedName || contact?.name || null;
    } catch (error) {
      console.error(JSON.stringify({
        event: "whatsapp_contact_name_lookup_failed",
        chat_id: resolvedChatId,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }

  return {
    // Kept as the first message id for backwards compatibility with existing callers and
    // tests; the full per-message list is in `messages`.
    whatsapp_message_id: firstSentMessage?.id?._serialized || null,
    messages: sent.map((entry) => ({
      whatsapp_message_id: entry.message?.id?._serialized || null,
      kind: entry.kind,
      attachment_index: entry.attachment_index,
    })),
    whatsapp_chat_id: resolvedChatId,
    whatsapp_identity_key: resolvedIdentity.canonicalChatId,
    whatsapp_normalized_phone: resolvedIdentity.normalizedPhone,
    whatsapp_contact_name: contactName,
    tenant_id: tenantId || null,
    provider: "whatsapp-service",
    external_account_id: externalAccountId,
    whatsapp_endpoint_id: whatsappEndpointId,
  };
}

async function sendSystemMessage({ to, message, external_account_id: externalAccountId, clientOverride, readyOverride }) {
  const activeClient = clientOverride || client;
  const isClientReady = readyOverride ?? ready;
  if (!activeClient || !isClientReady) {
    throw new Error("WhatsApp client is not ready");
  }

  if (!externalAccountId) {
    throw new Error("System WhatsApp send is missing external_account_id");
  }
  if (externalAccountId !== whatsappClientId) {
    throw new Error(`WhatsApp account id mismatch: requested ${externalAccountId} but this service is configured for ${whatsappClientId}`);
  }

  const chatId = normalizeRecipient(to);
  if (!chatId) {
    throw new Error("Invalid recipient phone number");
  }
  if (!message) {
    throw new Error("System WhatsApp send is missing message");
  }

  const sentMessage = await activeClient.sendMessage(chatId, message);

  // A recipient whose account uses @lid is reachable on their plain @c.us number, but every
  // inbound reply arrives filed under their @lid identity instead (same asymmetry documented
  // in sendTextMessage). Resolve that identity here so callers can attribute replies back to
  // this recipient - best-effort only, since a failed lookup must never fail a sent message.
  let identityKey = null;
  try {
    const [mapping] = await activeClient.getContactLidAndPhone([chatId]);
    identityKey = normalizeWhatsAppChatId(mapping?.lid) || null;
  } catch (error) {
    console.error(JSON.stringify({
      event: "whatsapp_system_send_lid_lookup_failed",
      chat_id: chatId,
      error: error instanceof Error ? error.message : String(error),
    }));
  }

  console.info(JSON.stringify({
    event: "whatsapp_system_send",
    message_id: sentMessage?.id?._serialized || null,
    chat_id: chatId,
    whatsapp_identity_key: identityKey,
  }));

  return {
    whatsapp_message_id: sentMessage?.id?._serialized || null,
    whatsapp_chat_id: chatId,
    whatsapp_identity_key: identityKey,
  };
}

// Backfill throttling. The CRM triggers /admin/backfill on every chat link/relink, and a burst of
// those (seen 2026-09: 261 calls in one hour on the SSI account) each launches a full-chat scan +
// history fetch. That volume of automation is what gets a linked device flagged and force-unlinked
// by WhatsApp. Two guards keep the footprint bounded regardless of caller behavior:
//   1. Serialization: only one backfill sweep runs at a time (chained on backfillChain).
//   2. De-dupe: identical requests (same chat/scope) within whatsappBackfillDedupeWindowMs coalesce
//      onto the in-flight/most-recent run instead of each starting their own scan.
let backfillChain = Promise.resolve();
const recentBackfillByKey = new Map(); // key -> { at, promise }

function backfillDedupeKey(options = {}) {
  return JSON.stringify({
    chatId: options.chatId ? String(options.chatId).trim() : null,
    all: Boolean(options.all),
    onlyOutbound: Boolean(options.onlyOutbound),
    limit: Number.isFinite(options.limit) ? options.limit : null,
  });
}

async function runHistoryBackfill(options = {}) {
  const key = backfillDedupeKey(options);
  const now = Date.now();
  const recent = recentBackfillByKey.get(key);
  if (recent && now - recent.at < whatsappBackfillDedupeWindowMs) {
    console.info(JSON.stringify({ event: "whatsapp_history_backfill_coalesced", dedupe_key: key }));
    return recent.promise;
  }

  const paceMs = options.postSyncDelayMs ?? whatsappBackfillPaceMs;
  // Chain after any in-flight sweep so two scans never hit WhatsApp Web concurrently. Swallow the
  // predecessor's rejection here so one failed backfill can't break the chain for later callers.
  const runPromise = backfillChain
    .catch(() => {})
    .then(() => backfillAllChats({ ...options, postSyncDelayMs: paceMs }));
  backfillChain = runPromise.catch(() => {});

  const entry = { at: now, promise: runPromise };
  recentBackfillByKey.set(key, entry);
  runPromise
    .finally(() => {
      // Extend the window to cover completion, and prune stale keys so the map can't grow unbounded.
      if (recentBackfillByKey.get(key) === entry) {
        entry.at = Date.now();
      }
      for (const [existingKey, value] of recentBackfillByKey) {
        if (Date.now() - value.at > whatsappBackfillDedupeWindowMs * 4) {
          recentBackfillByKey.delete(existingKey);
        }
      }
    })
    .catch(() => {});

  return runPromise;
}

async function runHistoryDebugSample({ chatCount = 3, messageLimit = 50, postSyncDelayMs = 1500 } = {}) {
  if (!client || !ready) {
    throw new Error("WhatsApp client is not ready");
  }

  const { chats } = await fetchChatModelsSafe(client, { wrap: true });
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
  clearLogoutStateResetTimer();
  openTeardownWindow("shutdown");

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
  getConnectionStatus,
  getLatestQr,
  resumeReconnect,
  sendTextMessage,
  sendSystemMessage,
  shutdownClient,
  runHistoryBackfill,
  backfillAllChats,
  runHistoryDebugSample,
  debugChatModelBuild,
  buildHistoryDedupeKey,
  sortBackfillMessages,
  listChats,
  forwardCrmMessage,
  forwardInboundMessage,
  forwardOutboundMessage,
  forwardOutboundCapturedMessage,
  __setLastReadyAtForTests: (value) => { lastReadyAt = Number(value) || 0; },
  __seedPendingOutboundTenantByMessageId: (id, tenantId) => { pendingOutboundTenantByMessageId.set(id, tenantId ?? null); },
  __hasPendingOutboundTenantByMessageId: (id) => pendingOutboundTenantByMessageId.has(id),
};




