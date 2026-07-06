const express = require("express");

function createMessageRouter({ requireApiKey, sendTextMessage, runHistoryBackfill, runHistoryDebugSample }) {
  const router = express.Router();

  router.post("/send", requireApiKey, async (req, res) => {
    try {
      const to = typeof req.body?.to === "string" ? req.body.to.trim() : "";
      const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";
      const tenantId = req.body?.tenant_id;

      if (!to || !message) {
        return res.status(400).json({
          ok: false,
          error: 'Both "to" and "message" are required.',
        });
      }

      await sendTextMessage(to, message, tenantId);
      return res.json({ ok: true });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to send WhatsApp message";
      let status = 500;
      if (message.includes("not ready")) {
        status = 503;
      } else if (message.includes("Invalid recipient phone number")) {
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
      console.info("[whatsapp] history backfill starting", { limit: Number.isFinite(limit) ? limit : null, onlyOutbound });
      const result = await runHistoryBackfill(Number.isFinite(limit) ? { limit, onlyOutbound } : { onlyOutbound });
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

  return router;
}

module.exports = {
  createMessageRouter,
};
