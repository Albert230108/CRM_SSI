// Puppeteer / WhatsApp Web page-teardown errors that whatsapp-web.js raises out of unguarded async
// event handlers (its `framenavigated` -> inject() path) and out of client.destroy(). They surface
// as unhandled rejections / uncaught exceptions, which would otherwise kill this process.
//
// Killing the process is much worse than the error itself: systemd tears Chrome down mid-write,
// which corrupts the LocalAuth session and forces a fresh QR scan. The page state is disposable at
// that point (the client re-initialises via scheduleReconnect), so these are logged and ignored.
//
// Every pattern below was confirmed in production journals for crm-whatsapp / crm-whatsapp-2:
//   "Execution context was destroyed"          navigation raced an in-flight evaluate()
//   "Execution context is not available"       same race, newer Puppeteer wording
//   "Attempted to use detached Frame"          frame torn down mid-call
//   "Failed to add page binding"               inject() re-ran on a page that still had the
//                                              onQRChangedEvent binding after a logout navigation
//   "Target closed" / TargetCloseError         CDP target gone during destroy()/logout
//   "Session closed"                           CDP session torn down
//   "Protocol error"                           generic CDP teardown race
const TRANSIENT_PAGE_ERROR_PATTERNS = [
  "Execution context was destroyed",
  "Execution context is not available",
  "Attempted to use detached Frame",
  "Failed to add page binding",
  "Target closed",
  "TargetCloseError",
  "Session closed",
  "Protocol error",
];

// Includes the error name so class-only signals (e.g. Puppeteer's TargetCloseError, whose message
// does not always repeat the class name) still match the patterns above.
function getErrorMessage(error) {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}`;
  }
  return String(error);
}

function isTransientPageError(error) {
  const message = getErrorMessage(error);
  return TRANSIENT_PAGE_ERROR_PATTERNS.some((pattern) => message.includes(pattern));
}

// A time-boxed "we are knowingly tearing the client down" window.
//
// A synchronous scope guard is not enough: the errors above arrive asynchronously from the dying
// page, routinely after the teardown call that caused them has already returned. While this window
// is open we know the client is being rebuilt anyway, so no error from it should be fatal.
function createTeardownWindow({ now = () => Date.now() } = {}) {
  let openUntil = 0;

  return {
    // Extends, never shortens: overlapping teardowns (a disconnect landing mid-restart) must not
    // let an earlier, shorter window close the guard early.
    open(graceMs) {
      const grace = Number.isFinite(graceMs) ? Math.max(0, graceMs) : 0;
      openUntil = Math.max(openUntil, now() + grace);
      return openUntil;
    },
    isOpen() {
      return now() < openUntil;
    },
    close() {
      openUntil = 0;
    },
  };
}

module.exports = {
  TRANSIENT_PAGE_ERROR_PATTERNS,
  createTeardownWindow,
  getErrorMessage,
  isTransientPageError,
};
