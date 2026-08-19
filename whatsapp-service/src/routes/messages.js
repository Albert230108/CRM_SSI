const express = require("express");

const {
  maxOutboundAttachmentBytes: defaultMaxOutboundAttachmentBytes,
  maxOutboundAttachmentsTotalBytes: defaultMaxOutboundAttachmentsTotalBytes,
} = require("../config");

function createMessageRouter({
  requireApiKey,
  sendTextMessage,
  sendSystemMessage,
  runHistoryBackfill,
  runHistoryDebugSample,
  debugChatModelBuild,
  listChats,
  maxOutboundAttachmentBytes = defaultMaxOutboundAttachmentBytes,
  maxOutboundAttachmentsTotalBytes = defaultMaxOutboundAttachmentsTotalBytes,
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

  return router;
}

module.exports = {
  createMessageRouter,
};
