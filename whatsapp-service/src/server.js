require("dotenv").config();

const crypto = require("crypto");
const express = require("express");

const { apiKey, port } = require("./config");
const { initializeClient, isReady, sendTextMessage, shutdownClient, runHistoryBackfill, runHistoryDebugSample, listChats } = require("./whatsappClient");
const { createMessageRouter } = require("./routes/messages");

function requireApiKey(req, res, next) {
  if (!apiKey) {
    return res.status(500).json({
      ok: false,
      error: "API key is not configured.",
    });
  }

  const provided = String(req.get("X-API-Key") || "");
  if (provided.length !== apiKey.length) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }

  try {
    if (!crypto.timingSafeEqual(Buffer.from(provided), Buffer.from(apiKey))) {
      return res.status(401).json({ ok: false, error: "Unauthorized" });
    }
  } catch (error) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }

  return next();
}

async function main() {
  const app = express();
  app.disable("x-powered-by");
  app.use(express.json({ limit: "256kb" }));

  app.use(createMessageRouter({ requireApiKey, sendTextMessage, runHistoryBackfill, runHistoryDebugSample, listChats }));

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
