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
  const chatId = overrides.whatsapp_chat_id || message?.chatId || message?.from || null;
  const author = message?.author || null;
  const sender = overrides.sender || author || message?.from || null;
  const recipient = overrides.to || message?.to || message?.from || null;

  return {
    direction,
    from: direction === "inbound" ? sender : null,
    sender: direction === "inbound" ? sender : null,
    sender_raw: direction === "inbound" ? sender : null,
    sender_normalized: direction === "inbound" ? normalizeWhatsAppId(sender) : null,
    to: direction === "outbound" ? recipient : null,
    recipient: direction === "outbound" ? recipient : null,
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

    console.info(
      "Successfully forwarded %s WhatsApp message to CRM: message_id=%s",
      contextLabel,
      payload.whatsapp_message_id,
    );
    if (payload.whatsapp_message_id) {
      forwardedMessageIds.add(payload.whatsapp_message_id);
    }
    return true;
  } finally {
    clearTimeout(timeout);
  }
}

async function forwardInboundMessage(message) {
  if (!message || message?.fromMe || message?.isStatus) {
    return false;
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

async function backfillChatHistory(chat, limit = whatsappHistoryBackfillLimit) {
  if (!chat) {
    return { forwarded: 0, skipped: 0 };
  }

  if (typeof chat.syncHistory === "function") {
    try {
      await chat.syncHistory();
    } catch (error) {
      console.warn("chat.syncHistory() failed for backfill; continuing with fetchMessages:", error);
    }
  }

  const messages = typeof chat.fetchMessages === "function"
    ? await chat.fetchMessages(limit)
    : [];
  const ordered = Array.isArray(messages)
    ? messages.slice().sort((a, b) => {
        const left = Number(a?.timestamp || 0);
        const right = Number(b?.timestamp || 0);
        return left - right;
      })
    : [];

  let forwarded = 0;
  let skipped = 0;
  const seenIds = new Set();

  for (const message of ordered) {
    const whatsappMessageId = message?.id?._serialized || null;
    if (!whatsappMessageId || seenIds.has(whatsappMessageId)) {
      skipped += 1;
      continue;
    }
    seenIds.add(whatsappMessageId);

    const text = extractText(message);
    if (!text) {
      skipped += 1;
      continue;
    }

    const direction = message?.fromMe ? "outbound" : "inbound";
    const payload = buildCrmPayload(message, direction, {
      to: direction === "outbound" ? normalizeRecipient(chat?.id?.user || chat?.id || message?.to || message?.from) : null,
      sender: message?.author || message?.from || null,
      whatsapp_chat_id: chat?.id?._serialized || chat?.id || message?.from || message?.to || null,
      whatsapp_message_id: whatsappMessageId,
    });

    try {
      await forwardCrmMessage(payload, `history-${direction}`);
      forwarded += 1;
    } catch (error) {
      skipped += 1;
      console.error("Failed to forward historical WhatsApp message to CRM:", error);
    }
  }

  return { forwarded, skipped };
}

async function backfillAllChats({ limit = whatsappHistoryBackfillLimit } = {}) {
  if (!client || !ready) {
    throw new Error("WhatsApp client is not ready");
  }

  const chats = typeof client.getChats === "function" ? await client.getChats() : [];
  const orderedChats = Array.isArray(chats)
    ? chats.slice().sort((a, b) => String(a?.id?._serialized || a?.id || "").localeCompare(String(b?.id?._serialized || b?.id || "")))
    : [];

  let forwarded = 0;
  let skipped = 0;

  for (const chat of orderedChats) {
    const result = await backfillChatHistory(chat, limit);
    forwarded += result.forwarded;
    skipped += result.skipped;
  }

  return { chats: orderedChats.length, forwarded, skipped };
}

async function maybeRunStartupBackfill() {
  if (!whatsappHistoryBackfillEnabled || startupBackfillTriggered) {
    return;
  }

  startupBackfillTriggered = true;
  try {
    const result = await backfillAllChats({ limit: whatsappHistoryBackfillLimit });
    console.info(
      "Startup WhatsApp history backfill finished: chats=%s forwarded=%s skipped=%s",
      result.chats,
      result.forwarded,
      result.skipped,
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
  void forwardOutboundMessage(sentMessage, chatId, to).catch((error) => {
    console.error("Failed to forward outbound WhatsApp message to CRM:", error);
  });
  return true;
}

async function runHistoryBackfill(options = {}) {
  return backfillAllChats(options);
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
};
