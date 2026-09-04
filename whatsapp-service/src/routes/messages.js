const express = require("express");
const QRCode = require("qrcode");

const {
  maxOutboundAttachmentBytes: defaultMaxOutboundAttachmentBytes,
  maxOutboundAttachmentsTotalBytes: defaultMaxOutboundAttachmentsTotalBytes,
  serviceUnitName: defaultServiceUnitName,
} = require("../config");
const { readServiceLogs: defaultReadServiceLogs } = require("../serviceLogs");

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function createMessageRouter({
  requireApiKey,
  sendTextMessage,
  sendSystemMessage,
  runHistoryBackfill,
  runHistoryDebugSample,
  debugChatModelBuild,
  listChats,
  getConnectionStatus,
  getLatestQr,
  resumeReconnect,
  // Auth guard for the read-only /admin/status and /admin/qr GETs that also accepts the API key as
  // a ?key= query param so the QR page can be opened directly in a browser. Falls back to the
  // header-only guard when not supplied.
  requireApiKeyForAdminGet = requireApiKey,
  maxOutboundAttachmentBytes = defaultMaxOutboundAttachmentBytes,
  maxOutboundAttachmentsTotalBytes = defaultMaxOutboundAttachmentsTotalBytes,
  serviceUnitName = defaultServiceUnitName,
  readServiceLogs = defaultReadServiceLogs,
}) {
  const router = express.Router();

  router.get("/chats", requireApiKey, async (req, res) => {
    try {
      const externalAccountId = typeof req.query?.external_account_id === "string" ? req.query.external_account_id.trim() : "";
      const search = typeof req.query?.search === "string" ? req.query.search.trim() : "";
      const limit = Number.parseInt(String(req.query?.limit || ""), 10);
      const offset = Number.parseInt(String(req.query?.offset || ""), 10);
      const result = await listChats({
        externalAccountId,
        search,
        limit: Number.isFinite(limit) ? limit : undefined,
        offset: Number.isFinite(offset) ? offset : undefined,
      });
      return res.json({ ok: true, ...result });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to fetch WhatsApp chat list";
      let status = 500;
      if (message.includes("not ready")) {
        status = 503;
      } else if (message.includes("account id mismatch")) {
        status = 400;
      }
      console.error("Failed to handle /chats request:", error);
      return res.status(status).json({ ok: false, error: message });
    }
  });

  router.post("/send", requireApiKey, async (req, res) => {
    try {
      const to = typeof req.body?.to === "string" ? req.body.to.trim() : "";
      const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";
      const tenantId = req.body?.tenant_id;
      const externalAccountId = typeof req.body?.external_account_id === "string" ? req.body.external_account_id.trim() : "";
      const whatsappEndpointId = req.body?.whatsapp_endpoint_id ?? null;

      const rawAttachments = Array.isArray(req.body?.attachments) ? req.body.attachments : [];
      const attachments = [];
      let attachmentsTotalBytes = 0;
      for (const item of rawAttachments) {
        if (!item || typeof item !== "object" || typeof item.data_base64 !== "string" || !item.data_base64) {
          return res.status(400).json({
            ok: false,
            error: "Each attachment requires a non-empty data_base64 string.",
          });
        }
        const sizeBytes = Buffer.byteLength(item.data_base64, "base64");
        if (sizeBytes > maxOutboundAttachmentBytes) {
          return res.status(413).json({
            ok: false,
            error: `Attachment "${item.filename || "unnamed"}" exceeds the ${maxOutboundAttachmentBytes} byte per-file limit.`,
          });
        }
        attachmentsTotalBytes += sizeBytes;
        if (attachmentsTotalBytes > maxOutboundAttachmentsTotalBytes) {
          return res.status(413).json({
            ok: false,
            error: `Attachments exceed the ${maxOutboundAttachmentsTotalBytes} byte total limit.`,
          });
        }
        attachments.push({
          filename: typeof item.filename === "string" && item.filename ? item.filename : "attachment",
          mime_type: typeof item.mime_type === "string" && item.mime_type ? item.mime_type : "application/octet-stream",
          data_base64: item.data_base64,
        });
      }

      console.info("[whatsapp] /send request body", {
        to,
        message,
        tenant_id: tenantId ?? null,
        external_account_id: externalAccountId || null,
        whatsapp_endpoint_id: whatsappEndpointId,
        attachment_count: attachments.length,
      });

      if (!to || (!message && attachments.length === 0)) {
        return res.status(400).json({
          ok: false,
          error: '"to" and either "message" or "attachments" are required.',
        });
      }
      if (tenantId == null) {
        console.error("[whatsapp] /send rejected because tenant_id is missing", {
          body: req.body || null,
        });
        return res.status(400).json({
          ok: false,
          error: 'tenant_id is required for tenant-scoped WhatsApp sends',
        });
      }

      const requireRegisteredRecipient = req.body?.require_registered_recipient === true;

      const result = await sendTextMessage({
        to,
        message,
        tenant_id: tenantId,
        external_account_id: externalAccountId,
        whatsapp_endpoint_id: whatsappEndpointId,
        attachments,
        require_registered_recipient: requireRegisteredRecipient,
      });
      return res.json({ ok: true, ...result });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to send WhatsApp message";
      let status = 500;
      if (typeof error?.statusCode === "number") {
        status = error.statusCode;
      } else if (message.includes("not ready")) {
        status = 503;
      } else if (message.includes("Invalid recipient phone number") || message.includes("account id mismatch") || message.includes("missing external_account_id")) {
        status = 400;
      } else if (message.includes("not a registered WhatsApp user")) {
        status = 422;
      }
      console.error("Failed to handle /send request:", error);
      return res.status(status).json({ ok: false, error: message });
    }
  });

  router.post("/send-system", requireApiKey, async (req, res) => {
    try {
      const to = typeof req.body?.to === "string" ? req.body.to.trim() : "";
      const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";
      const externalAccountId = typeof req.body?.external_account_id === "string" ? req.body.external_account_id.trim() : "";

      console.info("[whatsapp] /send-system request body", { to, message_length: message.length, external_account_id: externalAccountId || null });

      if (!to || !message) {
        return res.status(400).json({
          ok: false,
          error: '"to" and "message" are required.',
        });
      }
      if (!externalAccountId) {
        return res.status(400).json({
          ok: false,
          error: "external_account_id is required for system WhatsApp sends.",
        });
      }

      const result = await sendSystemMessage({ to, message, external_account_id: externalAccountId });
      return res.json({ ok: true, ...result });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to send system WhatsApp message";
      let status = 500;
      if (message.includes("not ready")) {
        status = 503;
      } else if (
        message.includes("Invalid recipient phone number")
        || message.includes("missing message")
        || message.includes("missing external_account_id")
        || message.includes("account id mismatch")
      ) {
        status = 400;
      }
      console.error("Failed to handle /send-system request:", error);
      return res.status(status).json({ ok: false, error: message });
    }
  });

  router.post("/admin/backfill", requireApiKey, async (req, res) => {
    console.info("[whatsapp] history sync endpoint hit", { path: "/admin/backfill", body: req.body || null, query: req.query || null });
    try {
      const limit = Number.parseInt(String(req.body?.limit || req.query?.limit || ""), 10);
      const onlyOutbound = String(req.body?.onlyOutbound ?? req.query?.onlyOutbound ?? "").toLowerCase() === "true";
      const all = String(req.body?.all ?? req.query?.all ?? "").toLowerCase() === "true";
      const chatId = typeof req.body?.chatId === "string" ? req.body.chatId.trim() : (typeof req.query?.chatId === "string" ? req.query.chatId.trim() : "");
      console.info("[whatsapp] history backfill starting", { limit: Number.isFinite(limit) ? limit : null, onlyOutbound, all, chatId: chatId || null });
      const result = await runHistoryBackfill({
        ...(Number.isFinite(limit) ? { limit } : {}),
        onlyOutbound,
        all,
        ...(chatId ? { chatId } : {}),
      });
      console.info("[whatsapp] history backfill finished", result);
      return res.json({ ok: true, ...result });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to backfill WhatsApp history";
      const status = message.includes("not ready") ? 503 : 500;
      console.error("Failed to handle /admin/backfill request:", error);
      return res.status(status).json({ ok: false, error: message });
    }
  });

  // Resume auto-reconnect after the LOGOUT-threshold guard paused it (see whatsappClient.js). Lets a
  // human bring the client back after the number has rested, without a full service restart.
  router.post("/admin/reconnect", requireApiKey, async (req, res) => {
    try {
      if (typeof resumeReconnect !== "function") {
        return res.status(501).json({ ok: false, error: "reconnect not supported" });
      }
      const result = resumeReconnect();
      console.info("[whatsapp] /admin/reconnect invoked", result);
      return res.json({ ok: true, ...result });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to resume WhatsApp reconnect";
      console.error("Failed to handle /admin/reconnect request:", error);
      return res.status(500).json({ ok: false, error: message });
    }
  });

  router.post("/admin/debug/whatsapp-history-sync", requireApiKey, async (req, res) => {
    console.info("[whatsapp] history debug endpoint hit", { path: "/admin/debug/whatsapp-history-sync", body: req.body || null, query: req.query || null });
    try {
      const limit = Number.parseInt(String(req.body?.limit || req.query?.limit || ""), 10);
      const onlyOutbound = String(req.body?.onlyOutbound ?? req.query?.onlyOutbound ?? "").toLowerCase() === "true";
      const chatCount = Number.parseInt(String(req.body?.chatCount || req.query?.chatCount || ""), 10);
      console.info("[whatsapp] history debug starting", { chatCount: Number.isFinite(chatCount) ? chatCount : 3, messageLimit: Number.isFinite(limit) ? limit : 50, onlyOutbound });
      const sample = await runHistoryDebugSample({
        chatCount: Number.isFinite(chatCount) ? chatCount : 3,
        messageLimit: Number.isFinite(limit) ? limit : 50,
        onlyOutbound,
      });
      console.info("[whatsapp] history debug finished", sample);
      return res.json({ ok: true, ...sample });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to debug WhatsApp history sync";
      const status = message.includes("not ready") ? 503 : 500;
      console.error("Failed to handle /admin/debug/whatsapp-history-sync request:", error);
      return res.status(status).json({ ok: false, error: message });
    }
  });

  router.post("/admin/debug/chat-model", requireApiKey, async (req, res) => {
    const chatId = typeof req.body?.chatId === "string" ? req.body.chatId.trim() : (typeof req.query?.chatId === "string" ? req.query.chatId.trim() : "");
    console.info("[whatsapp] chat model debug endpoint hit", { path: "/admin/debug/chat-model", chatId: chatId || null });
    try {
      if (!chatId) {
        return res.status(400).json({ ok: false, error: "chatId is required" });
      }
      const result = await debugChatModelBuild(chatId);
      console.info("[whatsapp] chat model debug finished", result);
      return res.json({ ok: true, ...result });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to debug chat model build";
      const status = message.includes("not ready") ? 503 : 500;
      console.error("Failed to handle /admin/debug/chat-model request:", error);
      return res.status(status).json({ ok: false, error: message });
    }
  });

  router.get("/admin/status", requireApiKeyForAdminGet, (req, res) => {
    try {
      const status = typeof getConnectionStatus === "function" ? getConnectionStatus() : {};
      return res.json({ ok: true, ...status });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to read WhatsApp status";
      console.error("Failed to handle /admin/status request:", error);
      return res.status(500).json({ ok: false, error: message });
    }
  });

  // Recent journal output for this instance, so logout/crash loops can be diagnosed from the CRM
  // admin UI without shell access. The QR art is stripped upstream in serviceLogs (it is a live
  // linking credential).
  router.get("/admin/logs", requireApiKeyForAdminGet, async (req, res) => {
    try {
      const requestedLines = Number.parseInt(String(req.query?.lines ?? ""), 10);
      const result = await readServiceLogs({
        unit: serviceUnitName,
        lines: Number.isFinite(requestedLines) ? requestedLines : 200,
      });
      return res.json({ ok: true, ...result });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to read service logs";
      console.error("Failed to handle /admin/logs request:", error);
      return res.status(500).json({ ok: false, error: message });
    }
  });

  router.get("/admin/qr", requireApiKeyForAdminGet, async (req, res) => {
    try {
      const status = typeof getConnectionStatus === "function" ? getConnectionStatus() : {};
      if (status.ready) {
        return res.json({ ok: true, ready: true, message: "already linked" });
      }

      const { qr, generated_at: generatedAt } = typeof getLatestQr === "function"
        ? getLatestQr()
        : { qr: null, generated_at: null };
      if (!qr) {
        return res.status(503).json({ ok: false, ready: false, error: "no QR available yet" });
      }

      const format = typeof req.query?.format === "string" ? req.query.format.trim().toLowerCase() : "";

      if (format === "json") {
        return res.json({ ok: true, ready: false, qr, generated_at: generatedAt });
      }

      if (format === "png") {
        const buffer = await QRCode.toBuffer(qr, { type: "png", width: 400, margin: 2 });
        res.setHeader("Content-Type", "image/png");
        res.setHeader("Cache-Control", "no-store");
        return res.end(buffer);
      }

      // Default: a self-contained page that a browser can open directly. It re-fetches itself every
      // 15s because the WhatsApp QR rotates roughly every 20s.
      const dataUrl = await QRCode.toDataURL(qr, { width: 400, margin: 2 });
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.setHeader("Cache-Control", "no-store");
      return res.end(`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="refresh" content="15" />
<title>WhatsApp link — ${escapeHtml(status.client_id || "")}</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; padding: 2rem; text-align: center; background: #f6f7f9; color: #111; }
  img { width: 320px; height: 320px; image-rendering: pixelated; }
  .card { display: inline-block; background: #fff; padding: 1.5rem 2rem; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  .muted { color: #666; font-size: .85rem; }
</style>
</head>
<body>
  <div class="card">
    <h1>Scan to link WhatsApp</h1>
    <p>Account: <strong>${escapeHtml(status.client_id || "unknown")}</strong></p>
    <img src="${dataUrl}" alt="WhatsApp QR code" />
    <p class="muted">On the phone: Settings &rarr; Linked Devices &rarr; Link a device.</p>
    <p class="muted">QR generated ${escapeHtml(generatedAt || "just now")} &middot; page auto-refreshes every 15s.</p>
    ${status.last_disconnect ? `<p class="muted">Last disconnect: ${escapeHtml(status.last_disconnect.reason)} at ${escapeHtml(status.last_disconnect.at)}</p>` : ""}
  </div>
</body>
</html>`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to render WhatsApp QR";
      console.error("Failed to handle /admin/qr request:", error);
      return res.status(500).json({ ok: false, error: message });
    }
  });

  return router;
}

module.exports = {
  createMessageRouter,
};
