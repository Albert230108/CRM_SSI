const fs = require("fs");
const path = require("path");

// Repeated-LOGOUT tracking has to outlive the process. It is what decides when to stop re-linking
// into a device WhatsApp keeps rejecting, and that decision is worthless if a restart resets it:
// before the teardown-window fix, a LOGOUT could crash the process, systemd would restart it, and
// the in-memory counter went back to 0 - so the "pause after N logouts" threshold was never reached
// no matter how many times WhatsApp unlinked us (observed 2026-09-04).
//
// Every operation is fail-soft. A missing, unreadable, or corrupt state file must degrade to
// in-memory-only behaviour, never break client startup or the disconnect handler.
const EMPTY_STATE = {
  consecutiveLogoutCount: 0,
  lastLogoutAt: 0,
  autoReconnectPaused: false,
};

function createReconnectStateStore({ filePath, logger = console } = {}) {
  if (!filePath) {
    // No path configured: behave exactly like the old in-memory-only code.
    return {
      load: () => ({ ...EMPTY_STATE }),
      save: () => false,
      clear: () => false,
      filePath: null,
    };
  }

  function load() {
    try {
      const raw = fs.readFileSync(filePath, "utf8");
      const parsed = JSON.parse(raw);
      return {
        consecutiveLogoutCount: Number.isFinite(parsed?.consecutiveLogoutCount)
          ? Math.max(0, parsed.consecutiveLogoutCount)
          : 0,
        lastLogoutAt: Number.isFinite(parsed?.lastLogoutAt)
          ? Math.max(0, parsed.lastLogoutAt)
          : 0,
        autoReconnectPaused: parsed?.autoReconnectPaused === true,
      };
    } catch (error) {
      if (error?.code !== "ENOENT") {
        logger.warn("Could not read WhatsApp reconnect state; starting from a clean slate:", error?.message || error);
      }
      return { ...EMPTY_STATE };
    }
  }

  function save(state) {
    try {
      fs.mkdirSync(path.dirname(filePath), { recursive: true });
      fs.writeFileSync(
        filePath,
        JSON.stringify({
          consecutiveLogoutCount: state?.consecutiveLogoutCount ?? 0,
          lastLogoutAt: state?.lastLogoutAt ?? 0,
          autoReconnectPaused: state?.autoReconnectPaused === true,
          updatedAt: Date.now(),
        }),
        "utf8",
      );
      return true;
    } catch (error) {
      logger.warn("Could not persist WhatsApp reconnect state:", error?.message || error);
      return false;
    }
  }

  function clear() {
    return save({ ...EMPTY_STATE });
  }

  return { load, save, clear, filePath };
}

module.exports = { EMPTY_STATE, createReconnectStateStore };
