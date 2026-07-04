require("dotenv").config();

function toInteger(value, fallback) {
  const parsed = Number.parseInt(String(value || ""), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

module.exports = {
  port: toInteger(process.env.PORT, 3000),
  apiKey: String(process.env.API_KEY || "").trim(),
  whatsappClientId: String(process.env.WHATSAPP_CLIENT_ID || "swifthk-whatsapp").trim(),
  reconnectDelayMs: Math.max(1000, toInteger(process.env.RECONNECT_DELAY_MS, 5000)),
  crmWebhookUrl: String(process.env.CRM_WEBHOOK_URL || "").trim(),
  crmWebhookSecret: String(process.env.CRM_WEBHOOK_SECRET || "").trim(),
  crmWebhookRouteToken: String(process.env.CRM_WEBHOOK_ROUTE_TOKEN || "").trim(),
  crmWebhookTimeoutMs: Math.max(1000, toInteger(process.env.CRM_WEBHOOK_TIMEOUT_MS, 5000)),
};
