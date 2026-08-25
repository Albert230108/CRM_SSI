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
const crmBackfillIdentitiesUrl = String(process.env.CRM_BACKFILL_IDENTITIES_URL || "").trim() || (crmApiBaseUrl ? `${crmApiBaseUrl}/webhooks/whatsapp/backfill-identities` : "");
const crmWhatsAppResolveUrl = String(process.env.CRM_WHATSAPP_RESOLVE_URL || "").trim() || (crmApiBaseUrl ? `${crmApiBaseUrl}/webhooks/whatsapp/resolve` : "");
const crmBackfillBatchUrl = String(process.env.CRM_BACKFILL_BATCH_URL || "").trim() || (crmApiBaseUrl ? `${crmApiBaseUrl}/webhooks/whatsapp/backfill-batch` : "");

module.exports = {
  port: toInteger(process.env.PORT, 3001),
  apiKey: String(process.env.API_KEY || "").trim(),
  whatsappClientId: String(process.env.WHATSAPP_CLIENT_ID || "edi-crm-whatsapp").trim(),
  // Pins the WhatsApp Web client build whatsapp-web.js loads. Without a pin, whatsapp-web.js
  // fetches whatever build WhatsApp is currently serving on every fresh browser session (i.e.
  // every service restart), so an unannounced WhatsApp-side rollout can silently break chat
  // parsing (seen 2026-07-15: a same-day WhatsApp Web update broke @lid chat model construction
  // account-wide). Bump this only after confirming the new version works; see .wwebjs_cache/
  // for other previously-seen versions to roll back to.
  whatsappWebVersion: String(process.env.WHATSAPP_WEB_VERSION || "2.3000.1043053164").trim(),
  reconnectDelayMs: Math.max(1000, toInteger(process.env.RECONNECT_DELAY_MS, 5000)),
  reconnectReplayGraceMs: Math.max(0, toInteger(process.env.WHATSAPP_RECONNECT_REPLAY_GRACE_MS, 20000)),
  crmWebhookUrl,
  crmWebhookSecret: String(process.env.CRM_WEBHOOK_SECRET || "").trim(),
  crmWebhookRouteToken: String(process.env.CRM_WEBHOOK_ROUTE_TOKEN || "").trim(),
  crmWebhookTimeoutMs: Math.max(1000, toInteger(process.env.CRM_WEBHOOK_TIMEOUT_MS, 5000)),
  crmApiBaseUrl,
  crmOutboundResolutionUrl,
  crmBackfillIdentitiesUrl,
  crmWhatsAppResolveUrl,
  crmBackfillBatchUrl,
  crmBackfillBatchTimeoutMs: Math.max(5000, toInteger(process.env.CRM_BACKFILL_BATCH_TIMEOUT_MS, 60000)),
  whatsappHistoryBackfillBatchSize: Math.max(1, toInteger(process.env.WHATSAPP_HISTORY_BACKFILL_BATCH_SIZE, 200)),
  whatsappHistoryBackfillEnabled: String(process.env.WHATSAPP_HISTORY_BACKFILL_ENABLED ?? "false").trim().toLowerCase() === "true",
  whatsappHistoryBackfillLimit: Math.max(1, toInteger(process.env.WHATSAPP_HISTORY_BACKFILL_LIMIT, 100)),
  forwardedMessageCacheTtlMs: Math.max(1000, toInteger(process.env.WHATSAPP_FORWARDED_MESSAGE_TTL_MS, 10 * 60 * 1000)),
  // Outbound attachments arrive base64-encoded in the JSON body, so the express limit must
  // clear 25MB of files (~33.4MB encoded) plus JSON escaping overhead.
  maxRequestBody: String(process.env.WHATSAPP_MAX_REQUEST_BODY || "40mb").trim(),
  maxOutboundAttachmentBytes: Math.max(1, toInteger(process.env.WHATSAPP_MAX_OUTBOUND_ATTACHMENT_BYTES, 10 * 1024 * 1024)),
  maxOutboundAttachmentsTotalBytes: Math.max(1, toInteger(process.env.WHATSAPP_MAX_OUTBOUND_TOTAL_BYTES, 25 * 1024 * 1024)),
  maxInboundMediaBytes: Math.max(1, toInteger(process.env.WHATSAPP_MAX_INBOUND_MEDIA_BYTES, 10 * 1024 * 1024)),
};
