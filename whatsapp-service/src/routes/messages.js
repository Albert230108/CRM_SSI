const express = require("express");

function createMessageRouter({ requireApiKey, sendTextMessage, runHistoryBackfill, runHistoryDebugSample, debugChatModelBuild, listChats }) {
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

      console.info("[whatsapp] /send request body", {
        to,
        message,
        tenant_id: tenantId ?? null,
        external_account_id: externalAccountId || null,
        whatsapp_endpoint_id: whatsappEndpointId,
      });

      if (!to || !message) {
        return res.status(400).json({
          ok: false,
          error: 'Both "to" and "message" are required.',
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

      const result = await sendTextMessage({
        to,
        message,
        tenant_id: tenantId,
        external_account_id: externalAccountId,
        whatsapp_endpoint_id: whatsappEndpointId,
      });
      return res.json({ ok: true, ...result });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to send WhatsApp message";
      let status = 500;
      if (message.includes("not ready")) {
        status = 503;
      } else if (message.includes("Invalid recipient phone number") || message.includes("account id mismatch") || message.includes("missing external_account_id")) {
        status = 400;
      }
      console.error("Failed to handle /send request:", error);
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
