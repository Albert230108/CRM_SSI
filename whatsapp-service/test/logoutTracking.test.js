const test = require('node:test');
const assert = require('node:assert/strict');

const { applyLogout, computeReconnectDelayMs, shouldPauseAutoReconnect } = require('../src/logoutTracking');

const WINDOW_MS = 15 * 60 * 1000;
const THRESHOLD = 5;
const BASE_DELAY_MS = 5000;
const MAX_DELAY_MS = 5 * 60 * 1000;

// The regression. Observed loop: authenticated -> ready -> ~5 min -> LOGOUT -> reconnect -> repeat.
// Every cycle reached `ready`, and the old `ready` handler zeroed the counters, so the pause
// threshold was unreachable no matter how many times WhatsApp unlinked the device. Counters must
// now accumulate across a flapping session, because a ready that lasts 5 minutes is not stable.
test('repeated LOGOUTs reach the pause threshold even when every cycle reaches ready', () => {
  let state = { consecutiveLogoutCount: 0, lastLogoutAt: 0 };
  let clock = 1_000_000;
  const fiveMinutes = 5 * 60 * 1000;

  const pausedAfter = [];
  for (let cycle = 1; cycle <= THRESHOLD; cycle += 1) {
    // A ready that does not survive readyStabilityMs must leave the counters untouched, so nothing
    // resets state here - that is precisely the bug being guarded against.
    clock += fiveMinutes;
    state = applyLogout(state, clock, WINDOW_MS);
    pausedAfter.push(shouldPauseAutoReconnect(state.consecutiveLogoutCount, THRESHOLD));
  }

  assert.deepEqual(pausedAfter, [false, false, false, false, true]);
  assert.equal(state.consecutiveLogoutCount, THRESHOLD);
});

test('a LOGOUT outside the window starts a fresh burst instead of compounding', () => {
  let state = { consecutiveLogoutCount: 0, lastLogoutAt: 0 };
  let clock = 1_000_000;

  state = applyLogout(state, clock, WINDOW_MS);
  state = applyLogout(state, clock + 1000, WINDOW_MS);
  assert.equal(state.consecutiveLogoutCount, 2);

  // Well past the window: an isolated logout must not inherit the earlier burst.
  clock += WINDOW_MS * 3;
  state = applyLogout(state, clock, WINDOW_MS);

  assert.equal(state.consecutiveLogoutCount, 1);
  assert.equal(state.lastLogoutAt, clock, 'a new burst reopens the window');
  assert.equal(shouldPauseAutoReconnect(state.consecutiveLogoutCount, THRESHOLD), false);
});

test('isolated logouts spaced beyond the window never trigger the pause', () => {
  let state = { consecutiveLogoutCount: 0, lastLogoutAt: 0 };
  let clock = 1_000_000;

  for (let i = 0; i < 20; i += 1) {
    clock += WINDOW_MS + 1;
    state = applyLogout(state, clock, WINDOW_MS);
    assert.equal(shouldPauseAutoReconnect(state.consecutiveLogoutCount, THRESHOLD), false);
  }

  assert.equal(state.consecutiveLogoutCount, 1);
});

test('reconnect delay backs off exponentially and is capped', () => {
  assert.equal(computeReconnectDelayMs(0, BASE_DELAY_MS, MAX_DELAY_MS), BASE_DELAY_MS);
  assert.equal(computeReconnectDelayMs(1, BASE_DELAY_MS, MAX_DELAY_MS), BASE_DELAY_MS);
  assert.equal(computeReconnectDelayMs(2, BASE_DELAY_MS, MAX_DELAY_MS), 10_000);
  assert.equal(computeReconnectDelayMs(3, BASE_DELAY_MS, MAX_DELAY_MS), 20_000);
  assert.equal(computeReconnectDelayMs(4, BASE_DELAY_MS, MAX_DELAY_MS), 40_000);

  // Never exceeds the cap, however long the flap runs.
  assert.equal(computeReconnectDelayMs(99, BASE_DELAY_MS, MAX_DELAY_MS), MAX_DELAY_MS);
});

test('applyLogout tolerates a missing/blank starting state', () => {
  // A real epoch timestamp: with no window recorded yet (0), the first logout is by definition
  // outside the window and opens a fresh one.
  const at = 1_700_000_000_000;

  assert.deepEqual(applyLogout(undefined, at, WINDOW_MS), { consecutiveLogoutCount: 1, lastLogoutAt: at });
  assert.deepEqual(applyLogout({}, at, WINDOW_MS), { consecutiveLogoutCount: 1, lastLogoutAt: at });
});
