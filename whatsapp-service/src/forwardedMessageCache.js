// Bounded, TTL-based replacement for an unbounded forwardedMessageIds Set. Also gates
// concurrent forward attempts (e.g. the explicit sendMessage path and the message_create
// listener both observing the same provider message id) so only one of them actually posts
// to the CRM webhook.
function createForwardedMessageCache({ ttlMs, now = () => Date.now() } = {}) {
  if (!Number.isFinite(ttlMs) || ttlMs <= 0) {
    throw new Error("createForwardedMessageCache requires a positive ttlMs");
  }

  const forwarded = new Map();
  const inFlight = new Set();

  function pruneExpired() {
    const current = now();
    for (const [id, expiresAt] of forwarded) {
      if (expiresAt <= current) {
        forwarded.delete(id);
      }
    }
  }

  function isForwarded(id) {
    if (!id) {
      return false;
    }
    pruneExpired();
    return forwarded.has(id);
  }

  function markForwarded(id) {
    if (!id) {
      return;
    }
    forwarded.set(id, now() + ttlMs);
  }

  // Returns true if the caller now owns this id and should proceed; false if another
  // in-flight attempt already claimed it. Messages without an id are never deduplicated,
  // so they always "claim" successfully.
  function claimInFlight(id) {
    if (!id) {
      return true;
    }
    if (inFlight.has(id)) {
      return false;
    }
    inFlight.add(id);
    return true;
  }

  function releaseInFlight(id) {
    if (!id) {
      return;
    }
    inFlight.delete(id);
  }

  return { isForwarded, markForwarded, claimInFlight, releaseInFlight };
}

module.exports = { createForwardedMessageCache };
