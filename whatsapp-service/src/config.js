require("dotenv").config();

function toInteger(value, fallback) {
  const parsed = Number.parseInt(String(value || ""), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function deriveOrigin(urlValue) {
  try {
    return new URL(urlValue).origin;
  } catch (error) {
    return "";
  }
}

const crmWebhookUrl = String(process.env.CRM_WEBHOOK_URL || "").trim();
const crmApiBaseUrl = String(process.env.CRM_API_BASE_URL || "").trim() || deriveOrigin(crmWebhookUrl);
const crmOutboundResolutionUrl = String(process.env.CRM_OUTBOUND_RESOLUTION_URL || "").trim() || (crmApiBaseUrl ? `${crmApiBaseUrl}/api/communications/whatsapp/outbound-resolution` : "");

module.exports = {
  port: toInteger(process.env.PORT, 3000),
  apiKey: String(process.env.API_KEY || "").trim(),
  whatsappClientId: String(process.env.WHATSAPP_CLIENT_ID || "swifthk-whatsapp").trim(),
  reconnectDelayMs: Math.max(1000, toInteger(process.env.RECONNECT_DELAY_MS, 5000)),
  crmWebhookUrl,
  crmWebhookSecret: String(process.env.CRM_WEBHOOK_SECRET || "").trim(),
  crmWebhookRouteToken: String(process.env.CRM_WEBHOOK_ROUTE_TOKEN || "").trim(),
  crmWebhookTimeoutMs: Math.max(1000, toInteger(process.env.CRM_WEBHOOK_TIMEOUT_MS, 5000)),
  crmApiBaseUrl,
  crmOutboundResolutionUrl,
  whatsappHistoryBackfillEnabled: String(process.env.WHATSAPP_HISTORY_BACKFILL_ENABLED || "").trim().toLowerCase() === "true",
  whatsappHistoryBackfillLimit: Math.max(1, toInteger(process.env.WHATSAPP_HISTORY_BACKFILL_LIMIT, 100)),
};
