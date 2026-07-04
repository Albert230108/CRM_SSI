const express = require("express");

function createMessageRouter({ requireApiKey, sendTextMessage }) {
  const router = express.Router();

  router.post("/send", requireApiKey, async (req, res) => {
    try {
      const to = typeof req.body?.to === "string" ? req.body.to.trim() : "";
      const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";

      if (!to || !message) {
        return res.status(400).json({
          ok: false,
          error: 'Both "to" and "message" are required.',
        });
      }

      await sendTextMessage(to, message);
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

  return router;
}

module.exports = {
  createMessageRouter,
};
