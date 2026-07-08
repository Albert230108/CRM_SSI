const qrcode = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

const {
  crmWebhookRouteToken,
  crmWebhookSecret,
  crmWebhookTimeoutMs,
  crmWebhookUrl,
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
  return (
    chat?.name ||
    chat?.formattedTitle ||
    chat?.contact?.pushname ||
    chat?.contact?.name ||
    chat?.id?._serialized ||
    null
  );
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

function extractText(message) {
  for (const key of ["body", "caption", "text", "content"]) {
    const value = message?.[key];
    if (value) {
      return String(value);
    }
  }
  return "";
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
  };
}

async function forwardCrmMessage(payload, contextLabel) {
  if (!crmWebhookUrl) {
    console.warn(`CRM WhatsApp webhook URL is not configured; ${contextLabel} messages will not be forwarded.`);
    return false;
  }

  if (payload.whatsapp_message_id && forwardedMessageIds.has(payload.whatsapp_message_id)) {
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

async function backfillChatHistory(chat, options = {}) {
  const limit = Math.max(1, Number.parseInt(String(options.limit || whatsappHistoryBackfillLimit || 100), 10) || whatsappHistoryBackfillLimit || 100);
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
      await sleep(Number.parseInt(String(options.postSyncDelayMs || 1500), 10) || 1500);
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
      deduped += 1;
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
    });

    try {
      await forwardCrmMessage(payload, `history-${direction}`);
      imported += 1;
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
    failed_count: failed,
  }));

  return { imported, deduped, failed, inbound, outbound, fetched };
}

async function backfillAllChats({ limit = whatsappHistoryBackfillLimit, postSyncDelayMs = 1500, clientOverride = null, readyOverride = null, all = false } = {}) {
  const activeClient = clientOverride || client;
  const isClientReady = readyOverride ?? ready;
  if (!activeClient || !isClientReady) {
    throw new Error("WhatsApp client is not ready");
  }

  const chats = typeof activeClient.getChats === "function" ? await activeClient.getChats() : [];
  const orderedChats = Array.isArray(chats)
    ? chats.slice().sort((a, b) => String(getChatId(a) || "").localeCompare(String(getChatId(b) || "")))
    : [];

  const chatsToSync = orderedChats.filter(isRelevantChat);
  const skippedChats = orderedChats.length - chatsToSync.length;

  let imported = 0;
  let deduped = 0;
  let failed = 0;
  let inbound = 0;
  let outbound = 0;
  let fetched = 0;

  for (const chat of chatsToSync) {
    try {
      const result = await backfillChatHistory(chat, { limit, postSyncDelayMs });
      imported += result.imported;
      deduped += result.deduped;
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
    crm_eligible_chats_count: chatsToSync.length,
    chats_synced_count: chatsToSync.length,
    skipped_chats_count: skippedChats,
    imported_count: imported,
    deduped_count: deduped,
    failed_count: failed,
    scope: all ? "all" : "crm_scoped",
    crm_identity_lookup_failed: false,
  }));

  return {
    scope: all ? "all" : "crm_scoped",
    total_chats_in_whatsapp: orderedChats.length,
    total_crm_eligible_chats: chatsToSync.length,
    total_synced_chats: chatsToSync.length,
    skipped_chats: skippedChats,
    chats: chatsToSync.length,
    scanned: orderedChats.length,
    fetched,
    inbound,
    outbound,
    imported,
    deduped,
    failed,
    crm_identity_lookup_failed: false,
  };
}

async function maybeRunStartupBackfill() {
  if (!whatsappHistoryBackfillEnabled || startupBackfillTriggered) {
    return;
  }

  startupBackfillTriggered = true;
  try {
    const result = await backfillAllChats({ limit: whatsappHistoryBackfillLimit, all: false, postSyncDelayMs: 1500 });
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
  return backfillAllChats({ ...options, postSyncDelayMs: options.postSyncDelayMs || 1500 });
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
};




