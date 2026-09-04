// Pure rules behind the repeated-LOGOUT backoff. Kept out of whatsappClient.js because this logic
// lives inside an event handler there, which is precisely why two defects in it survived the whole
// test suite: the counters could never actually reach the pause threshold.
//
//   1. A crash-restart reset the in-memory counters to 0 (fixed by persisting them, see
//      reconnectState.js, and by not crashing on teardown, see transientErrors.js).
//   2. The `ready` handler cleared the counters on every successful link - but in the observed loop
//      the client reaches ready and is force-unlinked ~5 minutes later, so `ready` alone is not
//      evidence WhatsApp accepted the device. Counters are now only cleared once a session has
//      survived readyStabilityMs.

// Advances the LOGOUT counter. The window is measured from the PREVIOUS logout, not from the first
// of the burst.
//
// This matters: anchoring the window to the first logout caps how high the counter can climb, and
// the observed loop (a LOGOUT roughly every 5 minutes, a 15-minute window) could only ever reach 4
// before the window elapsed and reset it - so the threshold of 5 was unreachable for exactly the
// flap it exists to catch. Measuring gap-to-previous means any sustained flap with a period shorter
// than windowMs keeps compounding, while genuinely isolated logouts still reset to a fresh burst.
function applyLogout({ consecutiveLogoutCount = 0, lastLogoutAt = 0 } = {}, at, windowMs) {
  const continuesBurst = lastLogoutAt > 0 && at - lastLogoutAt <= windowMs;

  return {
    consecutiveLogoutCount: continuesBurst ? consecutiveLogoutCount + 1 : 1,
    lastLogoutAt: at,
  };
}

function shouldPauseAutoReconnect(consecutiveLogoutCount, threshold) {
  return consecutiveLogoutCount >= threshold;
}

// Exponential backoff keyed off consecutive LOGOUTs, so we stop re-linking every few seconds into a
// device WhatsApp is actively rejecting (which itself reads as abuse and worsens the flagging).
function computeReconnectDelayMs(consecutiveLogoutCount, baseDelayMs, maxDelayMs) {
  if (consecutiveLogoutCount <= 1) {
    return baseDelayMs;
  }

  const backoff = baseDelayMs * 2 ** (consecutiveLogoutCount - 1);
  return Math.min(backoff, maxDelayMs);
}

module.exports = { applyLogout, computeReconnectDelayMs, shouldPauseAutoReconnect };
