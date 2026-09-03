require("dotenv").config();

const crypto = require("crypto");
const express = require("express");

const { apiKey, port, maxRequestBody } = require("./config");
const { initializeClient, isReady, sendTextMessage, sendSystemMessage, shutdownClient, runHistoryBackfill, runHistoryDebugSample, debugChatModelBuild, listChats, getConnectionStatus, getLatestQr } = require("./whatsappClient");
const { createMessageRouter } = require("./routes/messages");

function isValidApiKey(provided) {
  if (provided.length !== apiKey.length) {
    return false;
  }
  try {
    return crypto.timingSafeEqual(Buffer.from(provided), Buffer.from(apiKey));
  } catch (error) {
    return false;
  }
}

function requireApiKey(req, res, next) {
  if (!apiKey) {
    return res.status(500).json({
      ok: false,
      error: "API key is not configured.",
    });
  }

  if (!isValidApiKey(String(req.get("X-API-Key") || ""))) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }

  return next();
}

// Read-only variant for the /admin/status and /admin/qr GETs: also accepts the API key via the
// ?key= query param so the QR page can be opened directly in a browser (a plain navigation cannot
// set the X-API-Key header). Tradeoff: the key then appears in the URL and access logs, so this is
// used ONLY for these read-only endpoints.
function requireApiKeyForAdminGet(req, res, next) {
  if (!apiKey) {
    return res.status(500).json({
      ok: false,
      error: "API key is not configured.",
    });
  }

  const provided = String(req.get("X-API-Key") || req.query?.key || "");
  if (!isValidApiKey(provided)) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }

  return next();
}

async function main() {
  const app = express();
  app.disable("x-powered-by");
  app.use(express.json({ limit: maxRequestBody }));

  app.use(createMessageRouter({ requireApiKey, requireApiKeyForAdminGet, sendTextMessage, sendSystemMessage, runHistoryBackfill, runHistoryDebugSample, debugChatModelBuild, listChats, getConnectionStatus, getLatestQr }));

  app.use((err, req, res, next) => {
    console.error("Unhandled WhatsApp service error:", err);
    if (res.headersSent) {
      return next(err);
    }
    return res.status(500).json({
      ok: false,
      error: "Internal server error",
    });
  });

  const server = app.listen(port, "0.0.0.0", () => {
    console.log(`EDI_CRM WhatsApp service listening on port ${port}`);
    console.log(`WhatsApp client ready: ${isReady() ? "yes" : "no"}`);
  });

  void initializeClient().catch((error) => {
    console.error("WhatsApp client startup failed:", error);
  });

  let shuttingDown = false;
  const shutdown = async (signal) => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    console.log(`Received ${signal}; shutting down WhatsApp service.`);

    await new Promise((resolve) => {
      server.close(() => resolve());
    });
    await shutdownClient();
    process.exit(0);
  };

  process.on("SIGINT", () => {
    void shutdown("SIGINT").catch((error) => {
      console.error("Failed during SIGINT shutdown:", error);
      process.exit(1);
    });
  });
  process.on("SIGTERM", () => {
    void shutdown("SIGTERM").catch((error) => {
      console.error("Failed during SIGTERM shutdown:", error);
      process.exit(1);
    });
  });
}

main().catch((error) => {
  console.error("Fatal WhatsApp service error:", error);
  process.exit(1);
});
