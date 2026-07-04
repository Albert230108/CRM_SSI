const qrcode = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

const { crmWebhookSecret, crmWebhookTimeoutMs, crmWebhookUrl, reconnectDelayMs, whatsappClientId } = require("./config");

let client = null;
let ready = false;
let initializingPromise = null;
let reconnectTimer = null;
let shuttingDown = false;

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

function buildInboundPayload(message) {
  const rawSender = String(message?.author || message?.from || "").trim();
  const normalizedSender = normalizeWhatsAppId(message?.author || message?.from);
  const text = extractText(message);
  const timestamp = message?.timestamp;

  return {
    direction: "inbound",
    from: normalizedSender || rawSender || null,
    sender: normalizedSender || rawSender || null,
    sender_raw: rawSender || null,
    sender_normalized: normalizedSender || null,
    message: text,
    body: text,
    text,
    timestamp: Number.isFinite(Number(timestamp)) ? Number(timestamp) : Math.floor(Date.now() / 1000),
    whatsapp_message_id: message?.id?._serialized || null,
    whatsapp_chat_id: message?.from || null,
    whatsapp_author: message?.author || null,
    whatsapp_type: message?.type || null,
    is_group: Boolean(message?.from && String(message.from).endsWith("@g.us")),
  };
}

async function forwardInboundMessage(message) {
  if (!crmWebhookUrl) {
    console.warn("CRM WhatsApp webhook URL is not configured; inbound messages will not be forwarded.");
    return;
  }

  if (message?.fromMe || message?.isStatus) {
    return;
  }

  const text = extractText(message);
  if (!text) {
    return;
  }

  const payload = buildInboundPayload(message);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), crmWebhookTimeoutMs);

  try {
    const response = await fetch(crmWebhookUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(crmWebhookSecret ? { "X-Webhook-Secret": crmWebhookSecret } : {}),
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      const responseText = await response.text().catch(() => "");
      throw new Error(`CRM webhook responded with ${response.status}${responseText ? `: ${responseText}` : ""}`);
    }
  } finally {
    clearTimeout(timeout);
  }
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

  await client.sendMessage(chatId, message);
  return true;
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
};
