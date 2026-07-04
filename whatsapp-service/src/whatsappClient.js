const qrcode = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

const {
  crmWebhookRouteToken,
  crmWebhookSecret,
  crmWebhookTimeoutMs,
  crmWebhookUrl,
  reconnectDelayMs,
  whatsappClientId,
  whatsappHistoryBackfillLimit,
  whatsappHistoryBackfillEnabled,
} = require("./config");

let client = null;
let ready = false;
let initializingPromise = null;
let reconnectTimer = null;
let shuttingDown = false;
let startupBackfillTriggered = false;
let forwardedMessageIds = new Set();
let outboundCaptureCount = 0;

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

function buildCrmPayload(message, direction, overrides = {}) {
  const text = extractText(message);
  const timestamp = message?.timestamp;
  const chatId = overrides.whatsapp_chat_id || message?.chatId || message?.from || message?.to || null;
  const author = message?.author || null;
  const sender = overrides.sender || author || message?.from || null;
  const recipient = overrides.to || message?.to || message?.from || null;

  return {
    direction,
    from: sender,
    sender,
    sender_raw: sender,
    sender_normalized: normalizeWhatsAppId(sender),
    to: recipient,
    recipient,
    message: text,
    body: text,
    text,
    timestamp: Number.isFinite(Number(timestamp)) ? Number(timestamp) : Math.floor(Date.now() / 1000),
    whatsapp_message_id: message?.id?._serialized || overrides.whatsapp_message_id || null,
    whatsapp_chat_id: chatId,
    whatsapp_author: author,
    whatsapp_type: message?.type || null,
    whatsapp_client_id: whatsappClientId || null,
    provider: "whatsapp-service",
    external_account_id: whatsappClientId || null,
    is_group: Boolean(chatId && String(chatId).endsWith("@g.us")),
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

async function forwardOutboundMessage(message, chatId, recipient) {
  const text = extractText(message);
  if (!text) {
    return false;
  }

  const payload = buildCrmPayload(message, "outbound", {
    to: recipient || chatId || message?.to || null,
    whatsapp_chat_id: chatId || message?.from || message?.to || null,
    whatsapp_message_id: message?.id?._serialized || null,
  });
  return forwardCrmMessage(payload, "outbound");
}

async function forwardOutboundCapturedMessage(message, chatId, recipient, contextLabel = "outbound") {
  if (!message?.fromMe) {
    return false;
  }

  const sent = await forwardOutboundMessage(message, chatId, recipient);
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
  const onlyOutbound = Boolean(options.onlyOutbound);
  if (!chat) {
    return { imported: 0, deduped: 0, failed: 0, inbound: 0, outbound: 0, fetched: 0 };
  }

  if (!isRelevantChat(chat)) {
    return { imported: 0, deduped: 0, failed: 0, inbound: 0, outbound: 0, fetched: 0, skippedChat: true };
  }

  if (typeof chat.syncHistory === "function") {
    try {
      await chat.syncHistory();
      await sleep(Number.parseInt(String(options.postSyncDelayMs || 1500), 10) || 1500);
    } catch (error) {
      console.warn(JSON.stringify({
        event: "whatsapp_history_sync_failure",
        chat_id: chat?.id?._serialized || chat?.id || null,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }

  const messages = typeof chat.fetchMessages === "function" ? await chat.fetchMessages({ limit, fromMe: onlyOutbound ? true : undefined }) : [];
  const ordered = Array.isArray(messages)
    ? messages.slice().sort((a, b) => Number(a?.timestamp || 0) - Number(b?.timestamp || 0))
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
    if (!whatsappMessageId || seenIds.has(whatsappMessageId)) {
      deduped += 1;
      continue;
    }
    seenIds.add(whatsappMessageId);

    const text = extractText(message);
    if (!text) {
      deduped += 1;
      continue;
    }

    const direction = message?.fromMe ? "outbound" : "inbound";
    if (onlyOutbound && direction !== "outbound") {
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
        chat_id: chat?.id?._serialized || chat?.id || null,
        whatsapp_message_id: whatsappMessageId,
        direction,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }

  console.info(JSON.stringify({
    event: "whatsapp_history_chat_summary",
    chat_id: chat?.id?._serialized || chat?.id || null,
    fetched_count: fetched,
    inbound_count: inbound,
    outbound_count: outbound,
    imported_count: imported,
    deduped_count: deduped,
    failed_count: failed,
    only_outbound: onlyOutbound,
  }));

  return { imported, deduped, failed, inbound, outbound, fetched };
}

async function backfillAllChats({ limit = whatsappHistoryBackfillLimit, onlyOutbound = false, postSyncDelayMs = 1500 } = {}) {
  if (!client || !ready) {
    throw new Error("WhatsApp client is not ready");
  }

  const chats = typeof client.getChats === "function" ? await client.getChats() : [];
  const orderedChats = Array.isArray(chats)
    ? chats.slice().sort((a, b) => String(a?.id?.serialized || a?.id?._serialized || a?.id || "").localeCompare(String(b?.id?.serialized || b?.id?._serialized || b?.id || "")))
    : [];

  let scanned = 0;
  let imported = 0;
  let deduped = 0;
  let failed = 0;
  let inbound = 0;
  let outbound = 0;
  let fetched = 0;

  for (const chat of orderedChats) {
    scanned += 1;
    try {
      const result = await backfillChatHistory(chat, { limit, onlyOutbound, postSyncDelayMs });
      imported += result.imported;
      deduped += result.deduped;
      failed += result.failed;
      inbound += result.inbound;
      outbound += result.outbound;
      fetched += result.fetched;
      console.info(JSON.stringify({
        event: "whatsapp_history_sync_success",
        chat_id: chat?.id?._serialized || chat?.id || null,
        fetched_count: result.fetched,
        imported_count: result.imported,
      }));
    } catch (error) {
      failed += 1;
      console.error(JSON.stringify({
        event: "whatsapp_history_sync_failure",
        chat_id: chat?.id?._serialized || chat?.id || null,
        error: error instanceof Error ? error.message : String(error),
      }));
    }
  }

  console.info(JSON.stringify({
    event: "whatsapp_history_backfill_summary",
    chats_scanned_count: scanned,
    fetched_message_count: fetched,
    inbound_count: inbound,
    outbound_count: outbound,
    imported_count: imported,
    deduped_count: deduped,
    failed_count: failed,
    only_outbound: onlyOutbound,
  }));

  return { chats: orderedChats.length, scanned, fetched, inbound, outbound, imported, deduped, failed };
}

async function maybeRunStartupBackfill() {
  if (!whatsappHistoryBackfillEnabled || startupBackfillTriggered) {
    return;
  }

  startupBackfillTriggered = true;
  try {
    const result = await backfillAllChats({ limit: whatsappHistoryBackfillLimit, onlyOutbound: false, postSyncDelayMs: 1500 });
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
    void forwardOutboundCapturedMessage(message, message?.chatId || message?.to || message?.from || null, message?.to || null, "message_create").catch((error) => {
      console.error("Failed to forward outbound WhatsApp message to CRM:", error);
    });
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

async function sendTextMessage(to, message) {
  if (!client || !ready) {
    throw new Error("WhatsApp client is not ready");
  }

  const chatId = normalizeRecipient(to);
  if (!chatId) {
    throw new Error("Invalid recipient phone number");
  }

  const sentMessage = await client.sendMessage(chatId, message);
  void forwardOutboundCapturedMessage(sentMessage, chatId, to, "sendMessage").catch((error) => {
    console.error("Failed to forward outbound WhatsApp message to CRM:", error);
  });
  return true;
}

async function runHistoryBackfill(options = {}) {
  return backfillAllChats({ ...options, onlyOutbound: Boolean(options.onlyOutbound), postSyncDelayMs: options.postSyncDelayMs || 1500 });
}

async function runHistoryDebugSample({ chatCount = 3, messageLimit = 50, onlyOutbound = false, postSyncDelayMs = 1500 } = {}) {
  if (!client || !ready) {
    throw new Error("WhatsApp client is not ready");
  }

  const chats = typeof client.getChats === "function" ? await client.getChats() : [];
  const orderedChats = Array.isArray(chats)
    ? chats.slice().filter(isRelevantChat).sort((a, b) => String(a?.id?._serialized || a?.id || "").localeCompare(String(b?.id?._serialized || b?.id || ""))).slice(0, chatCount)
    : [];

  const samples = [];
  let totalMessages = 0;
  let inboundMessages = 0;
  let outboundMessages = 0;

  for (const chat of orderedChats) {
    try {
      if (typeof chat.syncHistory === "function") {
        await chat.syncHistory();
        await sleep(postSyncDelayMs);
      }
      const messages = typeof chat.fetchMessages === "function" ? await chat.fetchMessages({ limit: messageLimit, fromMe: onlyOutbound ? true : undefined }) : [];
      const ordered = Array.isArray(messages) ? messages.slice().sort((a, b) => Number(a?.timestamp || 0) - Number(b?.timestamp || 0)) : [];
      const chatSamples = ordered.slice(0, 10).map((message) => ({
        whatsapp_message_id: message?.id?._serialized || null,
        fromMe: Boolean(message?.fromMe),
      }));
      const chatInbound = ordered.filter((message) => !message?.fromMe).length;
      const chatOutbound = ordered.filter((message) => message?.fromMe).length;
      totalMessages += ordered.length;
      inboundMessages += chatInbound;
      outboundMessages += chatOutbound;
      samples.push({
        chat_id: chat?.id?._serialized || chat?.id || null,
        messages_count: ordered.length,
        inbound_count: chatInbound,
        outbound_count: chatOutbound,
        sample_messages: chatSamples,
      });
    } catch (error) {
      samples.push({
        chat_id: chat?.id?._serialized || chat?.id || null,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return {
    chats_scanned: orderedChats.length,
    total_messages: totalMessages,
    inbound_messages: inboundMessages,
    outbound_messages: outboundMessages,
    samples,
    only_outbound: onlyOutbound,
  };
}

async function shutdownClient() {
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
  runHistoryDebugSample,
};
